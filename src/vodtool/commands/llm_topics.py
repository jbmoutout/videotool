"""LLM-based topic segmentation command for vodtool."""

import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger("vodtool")


def build_topic_map(
    llm_topics: list[dict],
    chunks: list[dict],
) -> list[dict]:
    """
    Convert LLM topic output to vodtool topic_map format.

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
                        }
                    )
                    current_span_chunks = [chunk]

        # Finalize last span
        if current_span_chunks:
            spans.append(
                {
                    "start": current_span_chunks[0]["start"],
                    "end": current_span_chunks[-1]["end"],
                    "chunk_ids": [c["id"] for c in current_span_chunks],
                }
            )

        # Calculate duration
        duration = sum(s["end"] - s["start"] for s in spans)

        topic_map.append(
            {
                "topic_id": topic_id,
                "label": topic.get("label", f"Topic {i + 1}"),
                "summary": topic.get("summary", ""),
                "spans": spans,
                "chunk_ids": chunk_ids,
                "duration_seconds": duration,
                "duration_label": f"{int(duration // 60)} min",
                "chunk_count": len(chunk_ids),
            }
        )

    return topic_map


def llm_topics(
    project_path: Path,
    max_topics: Optional[int] = None,
) -> Optional[Path]:
    """
    Use LLM to segment transcript into topics.

    Args:
        project_path: Path to the project directory
        max_topics: Optional maximum number of topics

    Returns:
        Path to the topic_map_llm.json file, or None if failed
    """
    # Validate project directory
    if not project_path.exists():
        console.print(f"[red]Error: Project directory not found: {project_path}[/red]")
        return None

    if not project_path.is_dir():
        console.print(f"[red]Error: Not a directory: {project_path}[/red]")
        return None

    # Check for chunks.json
    chunks_path = project_path / "chunks.json"
    if not chunks_path.exists():
        console.print(f"[red]Error: chunks.json not found: {chunks_path}[/red]")
        console.print("Run 'vodtool chunks' first to create chunks.")
        return None

    # Load chunks
    console.print("[cyan]Loading chunks...[/cyan]")
    try:
        with chunks_path.open(encoding="utf-8") as f:
            chunks = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading chunks: {e}[/red]")
        return None

    logger.info(f"Loaded {len(chunks)} chunks")
    console.print(f"[cyan]Loaded {len(chunks)} chunks[/cyan]")

    # Get LLM client
    console.print("[cyan]Connecting to Anthropic API...[/cyan]")
    try:
        from vodtool.llm import get_anthropic_client, segment_topics_with_llm

        client = get_anthropic_client()
    except ImportError as e:
        console.print(f"[red]Error: {e}[/red]")
        return None
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        return None

    # Call LLM for topic segmentation
    console.print("[cyan]Analyzing transcript with LLM (this may take a moment)...[/cyan]")
    try:
        llm_result = segment_topics_with_llm(client, chunks, max_topics=max_topics)
    except Exception as e:
        console.print(f"[red]Error calling LLM: {e}[/red]")
        return None

    # Build topic map
    console.print("[cyan]Building topic map...[/cyan]")
    topic_map = build_topic_map(llm_result, chunks)

    # Validate coverage
    all_chunk_ids = {c["id"] for c in chunks}
    assigned_chunk_ids = set()
    for topic in topic_map:
        assigned_chunk_ids.update(topic["chunk_ids"])

    missing = all_chunk_ids - assigned_chunk_ids
    extra = assigned_chunk_ids - all_chunk_ids

    if missing:
        console.print(
            f"[yellow]Warning: {len(missing)} chunks not assigned to any topic[/yellow]"
        )
        logger.warning(f"Unassigned chunks: {missing}")

    if extra:
        console.print(
            f"[yellow]Warning: {len(extra)} chunk IDs from LLM not in chunks.json[/yellow]"
        )
        logger.warning(f"Unknown chunk IDs: {extra}")

    # Save topic map
    output_path = project_path / "topic_map_llm.json"
    console.print("[cyan]Saving topic map...[/cyan]")

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(topic_map, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved topic_map_llm.json: {output_path}")
    except Exception as e:
        console.print(f"[red]Error saving topic map: {e}[/red]")
        return None

    # Print summary
    console.print("\n[green]✓ LLM topic segmentation complete![/green]")
    console.print(f"[bold]Topics:[/bold] {len(topic_map)}")
    console.print(f"[bold]Output:[/bold] {output_path}")

    # Print topic table
    table = Table(title="Topics Identified")
    table.add_column("ID", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Chunks", style="blue")

    for topic in topic_map:
        table.add_row(
            topic["topic_id"],
            topic["label"],
            topic["duration_label"],
            str(topic["chunk_count"]),
        )

    console.print(table)

    return output_path
