"""LLM-based narrative beat detection for vodtool.

Sends the full transcript (with timestamps) to Claude in a single call
and receives topic segmentation + narrative beats (hook/build/peak/resolution).

This is the simplified pipeline: no chunks, no embeddings, no llm-topics.
The LLM does topic detection and beat detection in one pass.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.file_utils import safe_read_json, safe_write_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")

VALID_BEAT_TYPES = {"hook", "build", "peak", "resolution"}
LLM_TIMEOUT = 300  # 5 minutes — long transcripts need more time
MAX_RETRIES = 1

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by llm_beats."""
    return _last_error


def _format_transcript(segments: list[dict]) -> str:
    """
    Format transcript segments into natural paragraphs with periodic timestamps.

    Instead of one line per segment (which produces fragmented LLM output),
    concatenate text into flowing paragraphs with a timestamp marker every ~30s.
    This encourages the LLM to think in broad narrative arcs, not tiny fragments.
    """
    if not segments:
        return ""

    lines = []
    current_text_parts = []
    last_marker_time = -30.0  # force first marker

    for seg in segments:
        start = seg["start"]
        text = seg["text"].strip()
        if not text:
            continue

        # Insert a timestamp marker every ~30 seconds
        if start - last_marker_time >= 30.0:
            # Flush accumulated text
            if current_text_parts:
                lines.append(" ".join(current_text_parts))
                current_text_parts = []
            lines.append(f"\n[{start:.0f}s]")
            last_marker_time = start

        current_text_parts.append(text)

    # Flush remaining text
    if current_text_parts:
        lines.append(" ".join(current_text_parts))

    return "\n".join(lines)


def _build_beat_prompt(segments: list[dict]) -> str:
    """Build the narrative beat detection prompt from transcript segments."""
    transcript_text = _format_transcript(segments)

    return f"""You are a video editor's assistant analyzing a stream transcript.

For each topic below, identify the NARRATIVE BEATS — the structural
moments that define how a YouTube video should be cut from this material.

BEAT TYPES:
- HOOK: The most attention-grabbing moment. A provocative statement,
  surprising claim, or emotional peak that would make a viewer click.
  This is where the YouTube video should START.
- BUILD: Context and setup that gives the hook meaning. Background
  information, introductions, framing.
- PEAK: The highest-value segment — the core argument, the main
  discussion, the meat of the topic. This is what viewers came for.
- RESOLUTION: Wind-down, conclusions, transitions to next topic.
  Often skippable for YouTube.

RULES:
- Not every topic has all 4 beat types. A short tangent might only
  have a hook and peak.
- The hook is NOT always at the beginning. Often the most interesting
  moment is in the middle.
- Beats can overlap (a hook can also be the start of a peak).
- Return timestamps as seconds from stream start.
- Include a confidence score (0.0-1.0) for each beat.
- Include a short label describing what happens in each beat.
- Generate labels in the same language as the transcript.

OUTPUT FORMAT: Return ONLY valid JSON matching this schema:
{{
  "beats": [
    {{
      "topic_id": "...",
      "topic_label": "...",
      "beats": [
        {{"type": "hook|build|peak|resolution", "start_s": N, "end_s": N,
         "confidence": 0.0-1.0, "label": "short description"}}
      ]
    }}
  ]
}}

TRANSCRIPT:
{transcript_text}"""


def validate_beats(beats_data: dict, stream_duration: float) -> dict:
    """
    Validate and clean beats data from LLM output.

    Enforces:
    - Valid beat types (hook/build/peak/resolution)
    - start_s < end_s
    - Timestamps clamped to [0, stream_duration]
    - Confidence in [0.0, 1.0]
    - Drops invalid beats

    Returns cleaned beats_data.
    """
    if not isinstance(beats_data, dict) or "beats" not in beats_data:
        raise ValueError("beats_data must have a 'beats' key")

    cleaned_topics = []

    for topic in beats_data["beats"]:
        if not isinstance(topic, dict):
            continue

        topic_id = topic.get("topic_id", "")
        topic_label = topic.get("topic_label", "")
        raw_beats = topic.get("beats", [])

        if not isinstance(raw_beats, list):
            continue

        cleaned_beats = []
        for beat in raw_beats:
            if not isinstance(beat, dict):
                continue

            beat_type = beat.get("type", "")
            if beat_type not in VALID_BEAT_TYPES:
                logger.warning(f"Dropping beat with invalid type: {beat_type}")
                continue

            start_s = beat.get("start_s")
            end_s = beat.get("end_s")

            if not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
                logger.warning(f"Dropping beat with non-numeric timestamps")
                continue

            # Clamp to stream duration
            start_s = max(0, min(start_s, stream_duration))
            end_s = max(0, min(end_s, stream_duration))

            # Drop if start >= end after clamping
            if start_s >= end_s:
                logger.warning(f"Dropping beat where start_s >= end_s: {start_s} >= {end_s}")
                continue

            # Clamp confidence
            confidence = beat.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))

            cleaned_beats.append({
                "type": beat_type,
                "start_s": round(start_s, 2),
                "end_s": round(end_s, 2),
                "confidence": round(confidence, 2),
                "label": str(beat.get("label", "")),
            })

        if cleaned_beats:
            cleaned_topics.append({
                "topic_id": topic_id,
                "topic_label": topic_label,
                "beats": cleaned_beats,
            })

    return {"beats": cleaned_topics}


def _parse_beats_response(response_text: str) -> dict:
    """Parse LLM response and extract beats JSON."""
    response_text = response_text.strip()

    # Handle markdown code blocks
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}")

    # Accept both {"beats": [...]} and bare array
    if isinstance(data, list):
        data = {"beats": data}

    if not isinstance(data, dict) or "beats" not in data:
        raise ValueError("LLM response missing 'beats' key")

    return data


def detect_beats(
    project_path: Path,
    json_progress: bool = False,
) -> Optional[Path]:
    """
    Detect narrative beats from transcript using a single LLM call.

    Reads transcript_raw.json, sends to Claude, validates output,
    writes beats.json.

    Args:
        project_path: Path to the project directory
        json_progress: If True, emit JSON progress lines (for Tauri IPC)

    Returns:
        Path to beats.json, or None on failure
    """
    global _last_error
    _last_error = None

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Load transcript
    transcript_path = project_path / "transcript_raw.json"
    if not transcript_path.exists():
        _last_error = "transcript_raw.json not found — run 'vodtool transcribe' first"
        console.print(f"[red]Error: {_last_error}[/red]")
        return None

    transcript = safe_read_json(transcript_path)
    if transcript is None:
        _last_error = "Failed to read transcript_raw.json"
        return None

    segments = transcript.get("segments", [])
    if not segments:
        _last_error = "Transcript has no segments"
        console.print(f"[red]Error: {_last_error}[/red]")
        return None

    # Get stream duration from meta.json or last segment
    meta_path = project_path / "meta.json"
    meta = safe_read_json(meta_path) if meta_path.exists() else {}
    stream_duration = (meta or {}).get("duration_seconds")

    if not stream_duration:
        # Fallback: use last segment end time
        stream_duration = max(seg.get("end", 0) for seg in segments)

    logger.info(f"Loaded {len(segments)} transcript segments, duration: {stream_duration:.0f}s")

    # Build prompt
    prompt = _build_beat_prompt(segments)
    token_estimate = len(prompt) // 4
    logger.info(f"Prompt size: ~{token_estimate} tokens")

    # Call Claude
    console.print("[cyan]Analyzing narrative structure...[/cyan]")
    start_time = time.time()

    from vodtool.llm import get_anthropic_client

    try:
        client = get_anthropic_client()
    except (ImportError, ValueError) as e:
        _last_error = str(e)
        console.print(f"[red]Error: {e}[/red]")
        return None

    last_error_detail = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
                timeout=LLM_TIMEOUT,
            )

            response_text = response.content[0].text
            beats_data = _parse_beats_response(response_text)
            break

        except ValueError as e:
            # JSON parse / schema error — retry once
            last_error_detail = str(e)
            if attempt < MAX_RETRIES:
                logger.warning(f"Beat detection failed ({e}), retrying...")
                console.print(f"[yellow]Parse error, retrying...[/yellow]")
                continue
            _last_error = f"Beat detection failed after {MAX_RETRIES + 1} attempts: {e}"
            console.print(f"[red]Error: {_last_error}[/red]")
            return None

        except Exception as e:
            error_type = type(e).__name__
            _last_error = f"Claude API error: {error_type}: {e}"
            console.print(f"[red]Error: {_last_error}[/red]")
            return None

    elapsed = time.time() - start_time
    logger.info(f"Claude beat detection completed in {elapsed:.1f}s")

    # Validate and clean beats
    try:
        beats_data = validate_beats(beats_data, stream_duration)
    except ValueError as e:
        _last_error = f"Beat validation failed: {e}"
        console.print(f"[red]Error: {_last_error}[/red]")
        return None

    topic_count = len(beats_data["beats"])
    beat_count = sum(len(t["beats"]) for t in beats_data["beats"])

    if topic_count == 0:
        _last_error = "No topics/beats detected in transcript"
        console.print(f"[red]Error: {_last_error}[/red]")
        return None

    # Save beats.json
    output_path = project_path / "beats.json"
    if not safe_write_json(output_path, beats_data):
        _last_error = "Failed to write beats.json"
        return None

    console.print(f"\n[green]✓ Beat detection complete![/green]")
    console.print(f"[bold]Topics:[/bold] {topic_count}")
    console.print(f"[bold]Beats:[/bold] {beat_count}")
    console.print(f"[bold]Time:[/bold] {elapsed:.1f}s")
    console.print(f"[bold]Output:[/bold] {output_path}")

    return output_path
