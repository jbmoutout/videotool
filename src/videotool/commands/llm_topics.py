"""LLM-based topic segmentation command for videotool."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from videotool.utils.file_utils import safe_read_json, safe_write_json
from videotool.utils.pipeline import require_file
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by llm_topics."""
    return _last_error


def format_duration(seconds: float) -> str:
    """
    Format duration as human-readable string.

    Shows seconds for < 60s, otherwise minutes or hours.
    Examples: "45s", "2m 30s", "1h 15m"
    """
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes = int(seconds // 60)
    remaining_secs = int(seconds % 60)

    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        if mins:
            return f"{hours}h {mins}m"
        return f"{hours}h"

    if remaining_secs:
        return f"{minutes}m {remaining_secs}s"
    return f"{minutes}m"


def validate_topic_map(
    topic_map: list[dict],
    chunks: list[dict],
) -> dict[str, any]:
    """
    Validate topic map integrity and compute statistics.

    Enforces invariants:
    1. Every chunk assigned exactly once
    2. Topic spans are time-ordered
    3. No overlapping spans within a topic
    4. Duration = sum of span durations

    Args:
        topic_map: List of topics with spans and chunk_ids
        chunks: Original chunks list

    Returns:
        Dict with validation results:
        {
            "valid": bool,
            "errors": list[str],
            "warnings": list[str],
            "stats": {
                "total_chunks": int,
                "assigned_chunks": int,
                "unassigned_chunks": list[str],
                "duplicate_chunks": list[str],
                "total_duration": float,
                "topic_durations": list[float],
            }
        }
    """
    errors = []
    warnings = []

    # Build chunk lookup
    all_chunk_ids = {c["id"] for c in chunks}
    chunk_by_id = {c["id"]: c for c in chunks}

    # Track chunk assignments
    chunk_assignments: dict[str, list[str]] = {}  # chunk_id -> [topic_ids]

    total_duration = 0.0
    topic_durations = []

    for topic in topic_map:
        topic_id = topic["topic_id"]
        spans = topic["spans"]
        chunk_ids = topic["chunk_ids"]
        duration = topic.get("duration_seconds", 0)

        # Check chunk assignments
        for chunk_id in chunk_ids:
            if chunk_id not in all_chunk_ids:
                errors.append(f"{topic_id}: references unknown chunk {chunk_id}")
            else:
                chunk_assignments.setdefault(chunk_id, []).append(topic_id)

        # Validate spans are time-ordered and non-overlapping
        prev_end = None

        for i, span in enumerate(spans):
            start = span["start"]
            end = span["end"]

            if start >= end:
                errors.append(f"{topic_id} span {i}: start >= end ({start} >= {end})")

            if prev_end is not None and start < prev_end:
                errors.append(f"{topic_id} span {i}: overlaps previous span ({start} < {prev_end})")

            prev_end = end

        # Validate duration matches sum of chunk durations (not span boundaries)
        chunk_duration = sum(
            chunk_by_id[cid]["end"] - chunk_by_id[cid]["start"]
            for cid in chunk_ids
            if cid in chunk_by_id
        )
        duration_diff = abs(duration - chunk_duration)
        if duration_diff > 0.01:  # Allow 0.01s floating-point tolerance
            error_msg = (
                f"{topic_id}: duration_seconds ({duration:.2f}) "
                f"!= sum of chunks ({chunk_duration:.2f})"
            )
            errors.append(error_msg)

        total_duration += chunk_duration
        topic_durations.append(chunk_duration)

    # Find unassigned and duplicate chunks
    unassigned = []
    duplicates = []

    for chunk_id in all_chunk_ids:
        assignments = chunk_assignments.get(chunk_id, [])
        if not assignments:
            unassigned.append(chunk_id)
        elif len(assignments) > 1:
            duplicates.append(f"{chunk_id} assigned to {len(assignments)} topics: {assignments}")

    if unassigned:
        warnings.append(f"{len(unassigned)} chunks not assigned to any topic")

    if duplicates:
        errors.append(f"{len(duplicates)} chunks assigned to multiple topics")
        for dup in duplicates[:5]:  # Show first 5
            errors.append(f"  {dup}")

    # Compute stream total for comparison
    stream_duration = sum(c["end"] - c["start"] for c in chunks)

    if abs(total_duration - stream_duration) > 1.0:  # Allow 1s tolerance
        warnings.append(
            f"Topic total ({total_duration:.1f}s) != stream total ({stream_duration:.1f}s), "
            f"diff: {abs(total_duration - stream_duration):.1f}s",
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "total_chunks": len(all_chunk_ids),
            "assigned_chunks": len(chunk_assignments),
            "unassigned_chunks": unassigned,
            "duplicate_chunks": duplicates,
            "total_duration": total_duration,
            "stream_duration": stream_duration,
            "topic_durations": topic_durations,
        },
    }


def build_topic_map(
    llm_topics: list[dict],
    chunks: list[dict],
) -> list[dict]:
    """
    Convert LLM topic output to videotool topic_map format.

    Args:
        llm_topics: Topics from LLM with label, chunk_ids, summary
        chunks: Original chunks with id, start, end, text

    Returns:
        List of topics in topic_map.json format
    """
    # Build chunk lookup
    chunk_by_id = {c["id"]: c for c in chunks}

    topic_map = []

    for i, topic in enumerate(llm_topics):
        topic_id = f"topic_{i:04d}"
        chunk_ids = topic.get("chunk_ids", [])

        # Build spans from chunk_ids (group contiguous chunks)
        spans = []
        current_span_chunks = []

        for chunk_id in sorted(chunk_ids, key=lambda x: chunk_by_id.get(x, {}).get("start", 0)):
            chunk = chunk_by_id.get(chunk_id)
            if not chunk:
                logger.warning(f"Chunk {chunk_id} not found, skipping")
                continue

            if not current_span_chunks:
                # Start new span
                current_span_chunks.append(chunk)
            else:
                # Check if contiguous (within 5 seconds of previous chunk end)
                last_chunk = current_span_chunks[-1]
                if chunk["start"] - last_chunk["end"] < 5.0:
                    # Contiguous, add to current span
                    current_span_chunks.append(chunk)
                else:
                    # Gap detected, finalize current span and start new one
                    spans.append(
                        {
                            "start": current_span_chunks[0]["start"],
                            "end": current_span_chunks[-1]["end"],
                            "chunk_ids": [c["id"] for c in current_span_chunks],
                        },
                    )
                    current_span_chunks = [chunk]

        # Finalize last span
        if current_span_chunks:
            spans.append(
                {
                    "start": current_span_chunks[0]["start"],
                    "end": current_span_chunks[-1]["end"],
                    "chunk_ids": [c["id"] for c in current_span_chunks],
                },
            )

        # Calculate duration: sum of actual chunk durations (not span boundaries)
        # This correctly handles gaps between chunks within spans
        duration = sum(
            chunk_by_id[cid]["end"] - chunk_by_id[cid]["start"]
            for cid in chunk_ids
            if cid in chunk_by_id
        )

        topic_map.append(
            {
                "topic_id": topic_id,
                "label": topic.get("label", f"Topic {i + 1}"),
                "summary": topic.get("summary", ""),
                "spans": spans,
                "chunk_ids": chunk_ids,
                "duration_seconds": duration,
                "duration_label": format_duration(duration),
                "chunk_count": len(chunk_ids),
            },
        )

    return topic_map


def llm_topics(
    project_path: Path,
    max_topics: Optional[int] = None,
    provider: str = "auto",
    model: Optional[str] = None,
) -> Optional[Path]:
    """
    Use LLM to segment transcript into topics.

    Args:
        project_path: Path to the project directory
        max_topics: Optional maximum number of topics
        provider: LLM provider ("anthropic", "ollama", or "auto")
        model: Optional model override (e.g., "qwen2.5:3b" for Ollama)

    Returns:
        Path to the topic_map_llm.json file, or None if failed
    """
    global _last_error
    _last_error = None

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for chunks.json
    chunks_path = require_file(project_path, "chunks.json", stage_name="chunks")
    if chunks_path is None:
        _last_error = "chunks.json not found — run 'videotool chunks' first"
        return None

    # Load chunks
    console.print("[cyan]Loading chunks...[/cyan]")
    chunks = safe_read_json(chunks_path)
    if chunks is None:
        _last_error = "Failed to read chunks.json"
        return None

    logger.info(f"Loaded {len(chunks)} chunks")
    console.print(f"[cyan]Loaded {len(chunks)} chunks[/cyan]")

    # Load chat context if available (Twitch VODs)
    from videotool.utils.twitch import summarize_chat_for_prompt
    chat_context = summarize_chat_for_prompt(project_path / "chat.json")
    if chat_context:
        console.print("[dim]Chat replay found — including as topic signal[/dim]")

    # Call LLM for topic segmentation based on provider
    llm_result = None

    if provider == "auto":
        # Try Ollama first, fall back to Anthropic
        console.print("[cyan]Attempting local LLM (Ollama)...[/cyan]")
        try:
            from videotool.llm import segment_topics_with_local_llm

            llm_result = segment_topics_with_local_llm(
                chunks,
                model=model or "qwen2.5:3b",
                max_topics=max_topics,
                chat_context=chat_context,
            )
            console.print("[green]✓ Used local LLM (Ollama)[/green]")
        except (ImportError, ConnectionError) as e:
            console.print(f"[yellow]⚠ Local LLM unavailable: {e}[/yellow]")
            console.print("[cyan]→ Falling back to Anthropic API...[/cyan]")

            try:
                from videotool.llm import get_anthropic_client, segment_topics_with_llm

                client = get_anthropic_client()
                llm_result = segment_topics_with_llm(client, chunks, max_topics=max_topics, chat_context=chat_context)
                console.print("[green]✓ Used Anthropic API[/green]")
            except Exception as api_error:
                _last_error = f"Anthropic API error: {api_error}"
                console.print(f"[red]Error calling Anthropic API: {api_error}[/red]")
                return None

    elif provider == "ollama":
        # Force Ollama
        console.print("[cyan]Connecting to local LLM (Ollama)...[/cyan]")
        try:
            from videotool.llm import segment_topics_with_local_llm

            llm_result = segment_topics_with_local_llm(
                chunks,
                model=model or "qwen2.5:3b",
                max_topics=max_topics,
                chat_context=chat_context,
            )
            console.print("[green]✓ Used local LLM (Ollama)[/green]")
        except Exception as e:
            _last_error = f"Ollama error: {e}"
            console.print(f"[red]Error calling local LLM: {e}[/red]")
            return None

    elif provider == "anthropic":
        # Force Anthropic
        console.print("[cyan]Connecting to Anthropic API...[/cyan]")
        try:
            from videotool.llm import get_anthropic_client, segment_topics_with_llm

            client = get_anthropic_client()
            llm_result = segment_topics_with_llm(client, chunks, max_topics=max_topics, chat_context=chat_context)
            console.print("[green]✓ Used Anthropic API[/green]")
        except Exception as e:
            _last_error = f"Anthropic API error: {e}"
            console.print(f"[red]Error calling Anthropic API: {e}[/red]")
            return None

    if llm_result is None:
        _last_error = "Failed to get LLM response"
        console.print("[red]Error: Failed to get LLM response[/red]")
        return None

    # Build topic map
    console.print("[cyan]Building topic map...[/cyan]")
    topic_map = build_topic_map(llm_result, chunks)

    # Validate topic map
    console.print("[cyan]Validating topic map...[/cyan]")
    validation = validate_topic_map(topic_map, chunks)

    if validation["errors"]:
        _last_error = f"Topic map validation failed: {'; '.join(validation['errors'])}"
        console.print("[red]✗ Topic map validation failed:[/red]")
        for error in validation["errors"]:
            console.print(f"  [red]• {error}[/red]")
        return None

    if validation["warnings"]:
        for warning in validation["warnings"]:
            console.print(f"[yellow]⚠ {warning}[/yellow]")

    # Save topic map
    output_path = project_path / "topic_map_llm.json"
    console.print("[cyan]Saving topic map...[/cyan]")

    if not safe_write_json(output_path, topic_map):
        _last_error = "Failed to write topic_map_llm.json"
        return None

    logger.info(f"Saved topic_map_llm.json: {output_path}")

    # Print summary
    stats = validation["stats"]
    total_duration = stats["total_duration"]

    console.print("\n[green]✓ LLM topic segmentation complete![/green]")
    console.print(f"[bold]Topics:[/bold] {len(topic_map)}")
    console.print(f"[bold]Total Duration:[/bold] {format_duration(total_duration)}")
    assigned = stats["assigned_chunks"]
    total = stats["total_chunks"]
    console.print(f"[bold]Coverage:[/bold] {assigned}/{total} chunks")
    console.print(f"[bold]Output:[/bold] {output_path}")

    # Print topic table
    table = Table(title="Topics Identified")
    table.add_column("ID", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Duration", style="yellow", justify="right")
    table.add_column("Chunks", style="blue", justify="right")

    for topic in topic_map:
        table.add_row(
            topic["topic_id"],
            topic["label"],
            topic["duration_label"],
            str(topic["chunk_count"]),
        )

    console.print(table)

    return output_path
