"""List topics command for vodtool - display topics with labels and summaries."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


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


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def list_topics_command(
    project_path: Path, source: str = "auto",
) -> Optional[list[dict]]:
    """
    Display topics with labels, summaries, and durations.

    Args:
        project_path: Path to the project directory
        source: Topic map source ('auto', 'llm', 'labeled', 'basic')

    Returns:
        List of topics, or None if failed
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
            console.print("Run 'vodtool topics' or 'vodtool llm-topics' first.")
        else:
            expected = source_map[source][0]
            console.print(f"[red]Error: {expected} not found[/red]")
        return None

    # Load topic map
    topics = safe_read_json(topic_map_path)
    if topics is None:
        return None

    if not topics:
        console.print("[yellow]No topics found[/yellow]")
        return None

    # Sort by start time of first span
    topics_sorted = sorted(topics, key=lambda t: t["spans"][0]["start"] if t["spans"] else 0)

    # Calculate total duration
    total_duration = sum(t.get("duration_seconds", 0) for t in topics_sorted)

    # Print summary header
    console.print(f"\n[green]✓ Topics loaded from {topic_map_path.name}[/green]")
    console.print(f"[bold]Topics:[/bold] {len(topics_sorted)}")
    console.print(f"[bold]Total Duration:[/bold] {format_duration(total_duration)}")

    # Create table with same style as llm-topics
    table = Table(title="Topics")
    table.add_column("ID", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Duration", style="yellow", justify="right")
    table.add_column("Chunks", style="blue", justify="right")

    for topic in topics_sorted:
        topic_id = topic["topic_id"]
        label = topic.get("label", "")
        duration = topic.get("duration_seconds", 0)
        chunk_count = topic.get("chunk_count", len(topic.get("chunk_ids", [])))

        # Use new format_duration for better display of short topics
        duration_str = format_duration(duration)

        table.add_row(
            topic_id,
            label,
            duration_str,
            str(chunk_count),
        )

    console.print(table)

    return topics_sorted
