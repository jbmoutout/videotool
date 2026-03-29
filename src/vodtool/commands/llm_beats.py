"""LLM-based narrative beat detection for vodtool.

Sends the full transcript (with timestamps) to Claude in a single call
and receives topic segmentation + beats (highlight/core/context/chat/transition/break).

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

VALID_BEAT_TYPES = {"highlight", "core", "context", "chat", "transition", "break"}
LLM_MODEL = "claude-sonnet-4-6"
LLM_TIMEOUT = 300  # 5 minutes — long transcripts need more time
MAX_RETRIES = 1

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by llm_beats."""
    return _last_error


def _format_transcript(segments: list[dict]) -> str:
    """
    Format transcript segments with per-segment timestamps.

    Each segment gets its own line with [start-end] timestamps.
    This matches the format that produced the best results in manual testing.
    """
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if text:
            lines.append(f"[{seg['start']:.1f}-{seg['end']:.1f}] {text}")
    return "\n".join(lines)


def _build_beat_prompt(segments: list[dict], stream_duration: float) -> str:
    """Build the beat detection prompt from transcript segments."""
    transcript_text = _format_transcript(segments)

    return f"""You are a video editor's assistant. Your job is to segment a live stream
transcript into a COMPLETE timeline of topics and beats.

This is a react/discussion stream — the host reads articles, reacts to
media, gives political commentary, and interacts with chat.

CRITICAL RULE — FULL COVERAGE:
You must create topics that tile the ENTIRE stream from 0s to {stream_duration:.0f}s.
- The first topic's first beat must start at 0.0
- The last topic's last beat must end at {stream_duration:.0f}
- Every second of the stream must belong to exactly one topic
- Topics must be contiguous: topic N's last beat end_s = topic N+1's first beat start_s
This means you MUST create topics for intros, BRB breaks, chat/donation
sessions, transitions, and stream closings — not just the "interesting"
discussion topics.

TOPIC RULES:
- Each topic is a coherent subject or activity block displayed as a row
  in the editor timeline.
- Generate topic_label as a short punchy title (3-6 words). Borrow the
  host's actual words, verdict, or reaction from the transcript — not a
  neutral description of the subject. The title should capture the host's
  attitude, not just the topic.
- A topic should be at least 2 minutes. Merge very short tangents into
  the surrounding topic rather than creating tiny standalone topics.
- Create separate topics for: stream intro/countdown, BRB breaks, extended
  chat/donation sessions, transitions between subjects, and stream outro.
- Generate all labels and topic titles in the same language as the transcript.

BEAT TYPES — each beat is a segment within a topic:

  Content beats (editor evaluates for the final cut):
  - highlight: Clip-worthy moment. Provocative take, emotional peak,
    surprising claim, powerful argument.
  - core: Substantive discussion. Main analysis, key argument, the meat
    of the reaction or commentary.
  - context: Reading source material, setup, background. Needed to
    understand the core but lower energy.

  Structural beats (editor trims or cuts):
  - chat: Viewer interaction, reading donations, Q&A, tangents driven
    by chat rather than the topic.
  - transition: Moving between topics, wrapping up, "anyway let's talk
    about...", pulling up the next article.
  - break: BRB screens, silence, music-only, intro countdowns, outro/raid,
    technical difficulties.

BEAT RULES:
- Beats tile continuously within each topic: a beat's end_s = next beat's start_s.
- Not every topic has all beat types. A BRB is just one "break" beat.
  A chat session might be just "chat" beats. That's fine.
- Include a confidence score (0.0-1.0) and a short label per beat.
  Beat labels should borrow the host's actual words, or reactions from
  the transcript - not a neutral summary of the subject.
- Timestamps in seconds from stream start.

SELF-CHECK before returning:
1. First beat starts at 0.0?
2. Last beat ends at {stream_duration:.0f}?
3. No gaps between consecutive topics?
If any check fails, fix it by adding or extending topics.

OUTPUT FORMAT: Return ONLY valid JSON matching this schema:
{{
  "beats": [
    {{
      "topic_id": "...",
      "topic_label": "...",
      "beats": [
        {{"type": "highlight|core|context|chat|transition|break", "start_s": N, "end_s": N,
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
    - Valid beat types (highlight/core/context/chat/transition/break)
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

            cleaned_beats.append(
                {
                    "type": beat_type,
                    "start_s": round(start_s, 2),
                    "end_s": round(end_s, 2),
                    "confidence": round(confidence, 2),
                    "label": str(beat.get("label", "")),
                }
            )

        if cleaned_beats:
            cleaned_topics.append(
                {
                    "topic_id": topic_id,
                    "topic_label": topic_label,
                    "beats": cleaned_beats,
                }
            )

    return {"beats": cleaned_topics}


def _compute_gaps(beats_data: dict, stream_duration: float) -> list[dict]:
    """Find uncovered time ranges in the beat timeline."""
    covered = []
    for topic in beats_data["beats"]:
        for beat in topic["beats"]:
            covered.append((beat["start_s"], beat["end_s"]))
    covered.sort()

    merged = []
    for start, end in covered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    gaps = []
    prev_end = 0.0
    for start, end in merged:
        if start > prev_end + 1.0:
            gaps.append({"start_s": round(prev_end, 2), "end_s": round(start, 2)})
        prev_end = end
    if prev_end < stream_duration - 1.0:
        gaps.append({"start_s": round(prev_end, 2), "end_s": round(stream_duration, 2)})

    return gaps


def _parse_beats_response(response_text: str) -> dict:
    """Parse LLM response and extract beats JSON."""
    response_text = response_text.strip()

    # Handle markdown code blocks — strip fences robustly
    if response_text.startswith("```"):
        # Find the JSON object boundaries instead of assuming fence positions
        first_brace = response_text.find("{")
        last_brace = response_text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            response_text = response_text[first_brace : last_brace + 1]

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
    prompt = _build_beat_prompt(segments, stream_duration)
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
                model=LLM_MODEL,
                max_tokens=16384,
                temperature=0.3,
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

    # Compute coverage
    gaps = _compute_gaps(beats_data, stream_duration)
    total_gap = sum(g["end_s"] - g["start_s"] for g in gaps)
    coverage_pct = (1 - total_gap / stream_duration) * 100 if stream_duration > 0 else 0

    console.print(f"\n[green]✓ Beat detection complete![/green]")
    console.print(f"[bold]Topics:[/bold] {topic_count}")
    console.print(f"[bold]Beats:[/bold] {beat_count}")
    console.print(f"[bold]Coverage:[/bold] {coverage_pct:.1f}%")
    console.print(f"[bold]Time:[/bold] {elapsed:.1f}s")
    console.print(f"[bold]Output:[/bold] {output_path}")

    return output_path
