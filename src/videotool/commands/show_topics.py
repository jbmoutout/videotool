"""Show topics timeline command for videotool - display topic spans chronologically."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from videotool.utils.file_utils import safe_read_json
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def show_topics_command(
    project_path: Path, include_misc: bool = False,
) -> Optional[list[dict]]:
    """
    Display a chronological timeline of topic spans.

    Shows when topics appear and reappear throughout the video,
    making thread returns visible.

    Args:
        project_path: Path to the project directory
        include_misc: Include MISC bucket topics (short/singleton topics)

    Returns:
        List of timeline entries, or None if failed
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for topic_map.json (try labeled first, then unlabeled)
    labeled_path = project_path / "topic_map_labeled.json"
    unlabeled_path = project_path / "topic_map.json"

    if labeled_path.exists():
        topic_map_path = labeled_path
    elif unlabeled_path.exists():
        topic_map_path = unlabeled_path
    else:
        console.print(f"[red]Error: Topic map not found in {project_path}[/red]")
        console.print("Run 'videotool topics' first to create topic map.")
        return None

    # Load topic map
    topics = safe_read_json(topic_map_path)
    if topics is None:
        return None

    if not topics:
        console.print("[yellow]No topics found[/yellow]")
        return None

    # Build flat list of all spans with their topic info
    all_spans = []
    topic_span_counts = {}  # Track how many spans per topic for "return" detection
    misc_topic_ids = set()  # Topics that belong to MISC bucket

    for topic in topics:
        topic_id = topic["topic_id"]
        label = topic.get("label", topic_id)

        # Check if this is a MISC topic (short duration or singleton)
        is_misc = False
        total_span_duration = sum(
            span["end"] - span["start"] for span in topic["spans"]
        )
        total_chunks = sum(len(span["chunk_ids"]) for span in topic["spans"])

        # MISC criteria: < 90s total duration OR < 3 chunks
        if total_span_duration < 90 or total_chunks < 3:
            is_misc = True
            misc_topic_ids.add(topic_id)

        if is_misc and not include_misc:
            continue

        topic_span_counts[topic_id] = len(topic["spans"])

        for span_idx, span in enumerate(topic["spans"]):
            all_spans.append(
                {
                    "topic_id": topic_id,
                    "label": label,
                    "start": span["start"],
                    "end": span["end"],
                    "span_idx": span_idx,
                    "total_spans": len(topic["spans"]),
                    "chunk_count": len(span["chunk_ids"]),
                    "is_misc": is_misc,
                },
            )

    # Sort by start time
    all_spans.sort(key=lambda x: x["start"])

    # Track which topics we've seen for "return" detection
    seen_topics = set()

    # Print header
    console.print("\n[bold cyan]Topic Timeline[/bold cyan]")
    console.print(f"[dim]Source: {topic_map_path.name}[/dim]\n")

    if misc_topic_ids and not include_misc:
        console.print(
            f"[dim]({len(misc_topic_ids)} MISC topics hidden, use --include-misc to show)[/dim]\n",
        )

    # Print timeline
    timeline_entries = []

    for span in all_spans:
        topic_id = span["topic_id"]
        start_ts = format_timestamp(span["start"])
        end_ts = format_timestamp(span["end"])
        duration = span["end"] - span["start"]
        duration_min = int(duration // 60)
        duration_sec = int(duration % 60)

        # Check if this is a return
        is_return = topic_id in seen_topics
        seen_topics.add(topic_id)

        # Format the line
        misc_marker = " [MISC]" if span["is_misc"] else ""
        return_marker = " (return)" if is_return else ""

        # Show span index if topic has multiple spans
        if span["total_spans"] > 1:
            span_info = f" [{span['span_idx'] + 1}/{span['total_spans']}]"
        else:
            span_info = ""

        line = (
            f"{topic_id}{span_info}  "
            f"{start_ts}–{end_ts}  "
            f"({duration_min}m {duration_sec}s, {span['chunk_count']} chunks)"
            f"{misc_marker}{return_marker}"
        )

        if span["is_misc"]:
            console.print(f"[dim]{line}[/dim]")
        elif is_return:
            console.print(f"{line} [dim](return)[/dim]")
        else:
            console.print(line)

        timeline_entries.append(
            {
                "topic_id": topic_id,
                "label": span["label"],
                "start": span["start"],
                "end": span["end"],
                "duration": duration,
                "chunk_count": span["chunk_count"],
                "is_return": is_return,
                "is_misc": span["is_misc"],
            },
        )

    # Print summary
    console.print()

    # Count returns
    topics_with_returns = set()
    for entry in timeline_entries:
        if entry["is_return"]:
            topics_with_returns.add(entry["topic_id"])

    if topics_with_returns:
        console.print(
            f"[green]✓ {len(topics_with_returns)} topic(s) have returns "
            f"(appear multiple times)[/green]",
        )
    else:
        console.print("[yellow]No topic returns detected[/yellow]")

    return timeline_entries
