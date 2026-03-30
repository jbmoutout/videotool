"""Semantic chunking command for videotool."""

import logging
import re
from pathlib import Path
from typing import Optional

from rich.console import Console

from videotool.utils.file_utils import project_lock, safe_read_json, safe_write_json
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by create_chunks."""
    return _last_error


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using basic punctuation.

    Args:
        text: Input text to split

    Returns:
        List of sentences
    """
    # Split on sentence-ending punctuation followed by space or end of string
    sentences = re.split(r"([.!?]+(?:\s+|$))", text)

    # Reconstruct sentences with their punctuation
    result = []
    for i in range(0, len(sentences) - 1, 2):
        sentence = (sentences[i] + sentences[i + 1]).strip()
        if sentence:
            result.append(sentence)

    # Handle last item if odd number of splits
    if len(sentences) % 2 == 1 and sentences[-1].strip():
        result.append(sentences[-1].strip())

    return result


def create_semantic_chunks(
    segments: list[dict],
    min_duration: float = 5.0,
    max_duration: float = 25.0,
) -> list[dict]:
    """
    Create semantic chunks from Whisper segments.

    Splits segments into sentences, then merges to create chunks
    between min_duration and max_duration seconds.

    Args:
        segments: List of Whisper segments with start, end, text
        min_duration: Minimum chunk duration in seconds
        max_duration: Maximum chunk duration in seconds

    Returns:
        List of chunks with id, start, end, text
    """
    # First pass: split segments into sentence-level units
    sentence_units = []

    for seg in segments:
        sentences = split_into_sentences(seg["text"])

        if not sentences:
            continue

        # Estimate time per sentence (proportional to length)
        seg_duration = seg["end"] - seg["start"]
        total_chars = sum(len(s) for s in sentences)

        if total_chars == 0:
            continue

        current_time = seg["start"]
        for sentence in sentences:
            # Proportional time allocation
            sentence_duration = (len(sentence) / total_chars) * seg_duration
            sentence_end = current_time + sentence_duration

            sentence_units.append(
                {
                    "start": current_time,
                    "end": sentence_end,
                    "text": sentence,
                },
            )

            current_time = sentence_end

    if not sentence_units:
        return []

    # Second pass: merge into chunks respecting duration constraints
    chunks = []
    current_chunk = {
        "start": sentence_units[0]["start"],
        "end": sentence_units[0]["end"],
        "text": sentence_units[0]["text"],
    }

    for unit in sentence_units[1:]:
        current_duration = current_chunk["end"] - current_chunk["start"]
        combined_duration = unit["end"] - current_chunk["start"]

        # Merge if under min_duration OR if adding this unit keeps us under max_duration
        if current_duration < min_duration or combined_duration <= max_duration:
            current_chunk["end"] = unit["end"]
            current_chunk["text"] += " " + unit["text"]
        else:
            # Finalize current chunk and start new one
            chunks.append(current_chunk)
            current_chunk = {
                "start": unit["start"],
                "end": unit["end"],
                "text": unit["text"],
            }

    # Add final chunk
    chunks.append(current_chunk)

    # Third pass: add stable IDs
    for i, chunk in enumerate(chunks):
        chunk["id"] = f"chunk_{i:04d}"

    return chunks


def assign_speakers_to_chunks(
    chunks: list[dict],
    diarization_segments: list[dict],
    speaker_map: dict,
) -> None:
    """
    Assign speaker labels to chunks based on diarization overlap.

    Modifies chunks in-place by adding a 'speaker' field.

    Args:
        chunks: List of chunks with start/end times
        diarization_segments: List of diarization segments with start/end/speaker_id
        speaker_map: Mapping from speaker_id to role (MAIN_1, MAIN_2, OTHER)
    """
    # Build reverse mapping from speaker_id to role
    speaker_to_role = {}
    for main_speaker in speaker_map.get("main_speakers", []):
        speaker_to_role[main_speaker["speaker_id"]] = main_speaker["role"]
    for bg_speaker in speaker_map.get("background_speakers", []):
        speaker_to_role[bg_speaker["speaker_id"]] = "BACKGROUND"
    for other_speaker in speaker_map.get("other_speakers", []):
        speaker_to_role[other_speaker["speaker_id"]] = "OTHER"

    # For each chunk, find overlapping diarization segments and pick the one with max overlap
    for chunk in chunks:
        chunk_start = chunk["start"]
        chunk_end = chunk["end"]

        best_speaker_id = None
        max_overlap = 0.0

        for seg in diarization_segments:
            seg_start = seg["start"]
            seg_end = seg["end"]

            # Calculate overlap
            overlap_start = max(chunk_start, seg_start)
            overlap_end = min(chunk_end, seg_end)
            overlap = max(0.0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker_id = seg["speaker_id"]

        # Map speaker_id to role
        if best_speaker_id and best_speaker_id in speaker_to_role:
            chunk["speaker"] = speaker_to_role[best_speaker_id]
        else:
            chunk["speaker"] = "UNKNOWN"


def _process_chunks_locked(project_path: Path, segments: list[dict]) -> Optional[Path]:
    """
    Process chunks within project lock (internal helper).

    Args:
        project_path: Path to the project directory
        segments: List of transcript segments

    Returns:
        Path to the chunks.json file, or None if processing failed
    """
    # Create chunks
    console.print("[cyan]Creating semantic chunks (5-25 seconds)...[/cyan]")
    try:
        chunks = create_semantic_chunks(segments)
    except Exception as e:
        _last_error = f"Error creating chunks: {e}"
        console.print(f"[red]Error creating chunks: {e}[/red]")
        return None

    if not chunks:
        _last_error = "No chunks created from transcript"
        console.print("[yellow]Warning: No chunks created[/yellow]")
        return None

    logger.info(f"Created {len(chunks)} chunks")

    # Add speaker information if diarization files exist
    diarization_path = project_path / "diarization_segments.json"
    speaker_map_path = project_path / "speaker_map.json"

    if diarization_path.exists() and speaker_map_path.exists():
        console.print("[cyan]Adding speaker information...[/cyan]")
        diarization_data = safe_read_json(diarization_path)
        speaker_map_data = safe_read_json(speaker_map_path)

        if diarization_data and speaker_map_data:
            try:
                assign_speakers_to_chunks(chunks, diarization_data, speaker_map_data)
                logger.info("Added speaker labels to chunks")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not add speaker info: {e}[/yellow]")
                # Continue without speaker info
                for chunk in chunks:
                    chunk["speaker"] = "UNKNOWN"
        else:
            # JSON parsing failed
            console.print("[yellow]Warning: Could not load diarization files[/yellow]")
            for chunk in chunks:
                chunk["speaker"] = "UNKNOWN"
    else:
        # No diarization files, mark as UNKNOWN
        for chunk in chunks:
            chunk["speaker"] = "UNKNOWN"
        if not diarization_path.exists():
            console.print("[yellow]Note: Run 'videotool diarize' to add speaker information[/yellow]")

    # Save chunks.json
    chunks_path = project_path / "chunks.json"
    console.print("[cyan]Saving chunks...[/cyan]")

    if not safe_write_json(chunks_path, chunks):
        _last_error = "Failed to write chunks.json"
        return None

    logger.info(f"Saved chunks.json: {chunks_path}")

    # Print summary
    total_duration = chunks[-1]["end"] - chunks[0]["start"]
    avg_duration = total_duration / len(chunks)

    console.print("\n[green]✓ Chunking complete![/green]")
    console.print(f"[bold]Chunks:[/bold] {len(chunks)}")
    console.print(
        f"[bold]Total duration:[/bold] {total_duration:.1f}s ({total_duration/60:.1f} min)",
    )
    console.print(f"[bold]Average chunk:[/bold] {avg_duration:.1f}s")
    console.print(f"[bold]Output:[/bold] {chunks_path}")

    return chunks_path


def create_chunks(project_path: Path) -> Optional[Path]:
    """
    Split transcript into semantic chunks.

    Args:
        project_path: Path to the project directory

    Returns:
        Path to the chunks.json file, or None if chunking failed
    """
    global _last_error
    _last_error = None

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Acquire project lock to prevent concurrent modifications
    with project_lock(project_path):
        # Check for transcript_raw.json
        transcript_path = project_path / "transcript_raw.json"
        if not transcript_path.exists():
            _last_error = f"Transcript not found — run 'videotool transcribe' first"
            console.print(f"[red]Error: Transcript not found: {transcript_path}[/red]")
            console.print("Run 'videotool transcribe' first to create a transcript.")
            return None

        # Load transcript with validation
        console.print("[cyan]Loading transcript...[/cyan]")
        transcript_data = safe_read_json(transcript_path)
        if transcript_data is None:
            _last_error = "Failed to read transcript file"
            return None

        segments = transcript_data.get("segments", [])
        if not segments:
            _last_error = "No segments found in transcript"
            console.print("[yellow]Warning: No segments found in transcript[/yellow]")
            return None

        logger.info(f"Loaded {len(segments)} segments from transcript")

        return _process_chunks_locked(project_path, segments)
