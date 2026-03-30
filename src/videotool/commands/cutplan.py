"""Cut plan generation command for videotool."""

import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from videotool.utils.file_utils import safe_read_json
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")


def merge_contiguous_spans(spans: list[dict]) -> list[dict]:
    """
    Merge all spans from a topic into contiguous ranges.

    If we're keeping content before AND after a gap, the gap is part of the topic
    (could be music, pauses, transitions). Don't drop it.

    Args:
        spans: List of spans with start/end times

    Returns:
        List of merged spans (usually just one continuous span)
    """
    if not spans:
        return []

    # Sort by start time
    sorted_spans = sorted(spans, key=lambda s: s["start"])

    merged = [sorted_spans[0].copy()]

    for span in sorted_spans[1:]:
        last = merged[-1]

        # Always extend to cover the gap - it's part of the topic
        last["end"] = span["end"]
        if "chunk_ids" in last and "chunk_ids" in span:
            last["chunk_ids"] = last["chunk_ids"] + span["chunk_ids"]
        if "segment_ids" in last and "segment_ids" in span:
            last["segment_ids"] = last["segment_ids"] + span["segment_ids"]

    return merged


def compute_drop_spans(
    keep_spans: list[dict],
    total_duration: float,
    all_topics: list[dict],
    selected_topic_id: str,
) -> list[dict]:
    """
    Compute drop spans as complement of keep spans.

    Args:
        keep_spans: List of spans to keep
        total_duration: Total video duration
        all_topics: All topics to identify which topic owns each drop span
        selected_topic_id: ID of the selected topic

    Returns:
        List of drop spans with reasons
    """
    if not keep_spans:
        # Drop everything
        return [{"start": 0.0, "end": total_duration, "reason": "not_selected_topic"}]

    drop_spans = []

    # Drop span before first keep
    if keep_spans[0]["start"] > 0.0:
        # Identify which topic owns this span
        reason = identify_span_topic(0.0, keep_spans[0]["start"], all_topics, selected_topic_id)
        drop_spans.append({"start": 0.0, "end": keep_spans[0]["start"], "reason": reason})

    # Drop spans between keeps
    for i in range(len(keep_spans) - 1):
        gap_start = keep_spans[i]["end"]
        gap_end = keep_spans[i + 1]["start"]

        if gap_end > gap_start:
            reason = identify_span_topic(gap_start, gap_end, all_topics, selected_topic_id)
            drop_spans.append({"start": gap_start, "end": gap_end, "reason": reason})

    # Drop span after last keep
    if keep_spans[-1]["end"] < total_duration:
        reason = identify_span_topic(
            keep_spans[-1]["end"],
            total_duration,
            all_topics,
            selected_topic_id,
        )
        drop_spans.append({"start": keep_spans[-1]["end"], "end": total_duration, "reason": reason})

    return drop_spans


def identify_span_topic(
    start: float,
    end: float,
    all_topics: list[dict],
    selected_topic_id: str,
) -> str:
    """
    Identify which topic owns a time span.

    Args:
        start: Start time of span
        end: End time of span
        all_topics: All topics with spans
        selected_topic_id: ID of selected topic

    Returns:
        Reason string (e.g., "other_topic:topic_0001")
    """
    # Find topic that overlaps most with this span
    max_overlap = 0.0
    best_topic_id = None

    for topic in all_topics:
        if topic["topic_id"] == selected_topic_id:
            continue

        for topic_span in topic["spans"]:
            # Compute overlap
            overlap_start = max(start, topic_span["start"])
            overlap_end = min(end, topic_span["end"])
            overlap = max(0.0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_topic_id = topic["topic_id"]

    if best_topic_id:
        return f"other_topic:{best_topic_id}"
    return "other_topic:unknown"


def generate_cutplan(
    project_path: Path, topic: str, source: str = "auto",
) -> Optional[Path]:
    """
    Generate a cut plan for extracting a specific topic.

    Args:
        project_path: Path to the project directory
        topic: Topic ID to extract
        source: Topic map source ('auto', 'llm', 'labeled', 'basic')

    Returns:
        Path to the cutplan.json file, or None if generation failed
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Map source to filename(s)
    source_map = {
        "llm": ["topic_map_llm.json"],
        "labeled": ["topic_map_labeled.json"],
        "basic": ["topic_map.json"],
        "auto": ["topic_map_llm.json", "topic_map_labeled.json", "topic_map.json"],
    }

    if source not in source_map:
        console.print(f"[red]Error: Invalid source '{source}'[/red]")
        console.print("Valid options: auto, llm, labeled, basic")
        return None

    # Find topic map file
    topic_map_path = None
    for filename in source_map[source]:
        candidate = project_path / filename
        if candidate.exists():
            topic_map_path = candidate
            break

    if topic_map_path is None:
        if source == "auto":
            console.print("[red]Error: No topic map found[/red]")
            console.print("Run 'videotool topics' or 'videotool llm-topics' first.")
        else:
            expected = source_map[source][0]
            console.print(f"[red]Error: {expected} not found[/red]")
            console.print("Run the appropriate command to generate it first.")
        return None

    # Load metadata for total duration
    meta_path = project_path / "meta.json"
    if not meta_path.exists():
        console.print(f"[red]Error: Metadata not found: {meta_path}[/red]")
        return None

    # Load topic map
    console.print(f"[cyan]Loading topic map from {topic_map_path.name}...[/cyan]")

    topics = safe_read_json(topic_map_path)
    if topics is None:
        return None

    if not topics:
        console.print("[yellow]Warning: No topics found[/yellow]")
        return None

    # Load metadata
    metadata = safe_read_json(meta_path)
    if metadata is None:
        return None

    total_duration = metadata.get("duration_seconds")
    if total_duration is None:
        console.print("[yellow]Warning: Duration not found in metadata[/yellow]")
        # Estimate from last topic span
        max_end = 0.0
        for t in topics:
            for span in t["spans"]:
                max_end = max(max_end, span["end"])
        total_duration = max_end
        logger.info(f"Estimated total duration: {total_duration:.1f}s")

    logger.info(f"Loaded {len(topics)} topics")

    # Find selected topic
    selected_topic = None
    for t in topics:
        if t["topic_id"] == topic:
            selected_topic = t
            break

    if selected_topic is None:
        console.print(f"[red]Error: Topic '{topic}' not found[/red]")
        console.print("\nAvailable topics:")
        for t in topics:
            label = t.get("label", t.get("label_stub", ""))
            console.print(f"  {t['topic_id']}: {label}")
        return None

    topic_label = selected_topic.get("label", selected_topic.get("label_stub", ""))
    console.print(f"[cyan]Generating cut plan for topic: {topic}[/cyan]")
    if topic_label:
        console.print(f"[dim]Label: {topic_label}[/dim]")

    # Extract keep spans
    keep_spans = [span.copy() for span in selected_topic["spans"]]

    # Merge spans into contiguous ranges (gaps between spans are kept)
    console.print("[cyan]Merging spans into contiguous ranges...[/cyan]")
    keep_spans = merge_contiguous_spans(keep_spans)

    logger.info(f"Keep spans after merging: {len(keep_spans)}")

    # Compute drop spans
    console.print("[cyan]Computing drop spans...[/cyan]")
    drop_spans = compute_drop_spans(keep_spans, total_duration, topics, topic)

    # Calculate total keep time
    total_keep = sum(span["end"] - span["start"] for span in keep_spans)

    # Build cut plan
    cutplan = {
        "selected_topic_id": topic,
        "selected_topic_label": topic_label,
        "keep_spans": [{"start": s["start"], "end": s["end"]} for s in keep_spans],
        "drop_spans": drop_spans,
        "total_keep_seconds": total_keep,
        "total_drop_seconds": total_duration - total_keep,
        "compression_ratio": total_keep / total_duration if total_duration > 0 else 0.0,
    }

    # Save cutplan.json
    output_path = project_path / "cutplan.json"

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(cutplan, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved cutplan.json: {output_path}")
    except Exception as e:
        console.print(f"[red]Error saving cut plan: {e}[/red]")
        return None

    # Validation
    total_drop = sum(span["end"] - span["start"] for span in drop_spans)
    coverage = total_keep + total_drop

    if abs(coverage - total_duration) > 1.0:  # Allow 1 second tolerance
        console.print("[yellow]Warning: Coverage mismatch[/yellow]")
        logger.warning(
            f"Keep: {total_keep:.1f}s, Drop: {total_drop:.1f}s, Total: {total_duration:.1f}s",
        )

    # Print summary
    console.print("\n[green]✓ Cut plan generated![/green]")
    console.print(f"[bold]Topic:[/bold] {topic}")
    if topic_label:
        console.print(f"[bold]Label:[/bold] {topic_label}")
    console.print(f"[bold]Keep spans:[/bold] {len(keep_spans)}")
    console.print(f"[bold]Drop spans:[/bold] {len(drop_spans)}")
    console.print(f"[bold]Total keep:[/bold] {total_keep:.1f}s ({total_keep/60:.1f} min)")
    console.print(
        f"[bold]Total drop:[/bold] {total_duration - total_keep:.1f}s "
        f"({(total_duration - total_keep)/60:.1f} min)",
    )
    console.print(f"[bold]Compression:[/bold] {cutplan['compression_ratio']*100:.1f}%")
    console.print(f"[bold]Output:[/bold] {output_path}")
    console.print(
        "\n[yellow]Note: This is a suggest-only plan. No files have been modified.[/yellow]",
    )

    return output_path
