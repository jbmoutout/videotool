"""Semantic chunking command for vodtool."""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()
logger = logging.getLogger("vodtool")


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using basic punctuation.

    Args:
        text: Input text to split

    Returns:
        List of sentences
    """
    # Split on sentence-ending punctuation followed by space or end of string
    sentences = re.split(r'([.!?]+(?:\s+|$))', text)

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

            sentence_units.append({
                "start": current_time,
                "end": sentence_end,
                "text": sentence,
            })

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
        unit_duration = unit["end"] - unit["start"]
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


def create_chunks(project_path: Path) -> Optional[Path]:
    """
    Split transcript into semantic chunks.

    Args:
        project_path: Path to the project directory

    Returns:
        Path to the chunks.json file, or None if chunking failed
    """
    # Validate project directory
    if not project_path.exists():
        console.print(f"[red]Error: Project directory not found: {project_path}[/red]")
        return None

    if not project_path.is_dir():
        console.print(f"[red]Error: Not a directory: {project_path}[/red]")
        return None

    # Check for transcript_raw.json
    transcript_path = project_path / "transcript_raw.json"
    if not transcript_path.exists():
        console.print(f"[red]Error: Transcript not found: {transcript_path}[/red]")
        console.print("Run 'vodtool transcribe' first to create a transcript.")
        return None

    # Load transcript
    console.print(f"[cyan]Loading transcript...[/cyan]")
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading transcript: {e}[/red]")
        return None

    segments = transcript_data.get("segments", [])
    if not segments:
        console.print("[yellow]Warning: No segments found in transcript[/yellow]")
        return None

    logger.info(f"Loaded {len(segments)} segments from transcript")

    # Create chunks
    console.print(f"[cyan]Creating semantic chunks (5-25 seconds)...[/cyan]")
    try:
        chunks = create_semantic_chunks(segments)
    except Exception as e:
        console.print(f"[red]Error creating chunks: {e}[/red]")
        return None

    if not chunks:
        console.print("[yellow]Warning: No chunks created[/yellow]")
        return None

    logger.info(f"Created {len(chunks)} chunks")

    # Save chunks.json
    chunks_path = project_path / "chunks.json"
    console.print(f"[cyan]Saving chunks...[/cyan]")

    try:
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved chunks.json: {chunks_path}")
    except Exception as e:
        console.print(f"[red]Error saving chunks: {e}[/red]")
        return None

    # Print summary
    total_duration = chunks[-1]["end"] - chunks[0]["start"]
    avg_duration = total_duration / len(chunks)

    console.print(f"\n[green]✓ Chunking complete![/green]")
    console.print(f"[bold]Chunks:[/bold] {len(chunks)}")
    console.print(f"[bold]Total duration:[/bold] {total_duration:.1f}s ({total_duration/60:.1f} min)")
    console.print(f"[bold]Average chunk:[/bold] {avg_duration:.1f}s")
    console.print(f"[bold]Output:[/bold] {chunks_path}")

    return chunks_path
