"""List topics command for vodtool - display topics with labels and summaries."""

import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger("vodtool")


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def list_topics_command(
    project_path: Path, source: str = "auto"
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
    if not project_path.exists():
        console.print(f"[red]Error: Project directory not found: {project_path}[/red]")
        return None

    if not project_path.is_dir():
        console.print(f"[red]Error: Not a directory: {project_path}[/red]")
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
    try:
        with topic_map_path.open(encoding="utf-8") as f:
            topics = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading topic map: {e}[/red]")
        return None

    if not topics:
        console.print("[yellow]No topics found[/yellow]")
        return None

    # Sort by start time of first span
    topics_sorted = sorted(topics, key=lambda t: t["spans"][0]["start"] if t["spans"] else 0)

    # Calculate total duration
    total_duration = sum(t.get("duration_seconds", 0) for t in topics_sorted)

    # Print header
    console.print()
    console.print(f"[bold cyan]Topics[/bold cyan] [dim]({topic_map_path.name})[/dim]")
    console.print()

    # Create table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=4)
    table.add_column("ID", style="cyan", width=12)
    table.add_column("Duration", justify="right", width=8)
    table.add_column("Label", width=40)

    for i, topic in enumerate(topics_sorted):
        topic_id = topic["topic_id"]
        label = topic.get("label", "")
        duration = topic.get("duration_seconds", 0)
        duration_str = format_timestamp(duration)

        table.add_row(
            str(i + 1),
            topic_id,
            duration_str,
            label,
        )

    console.print(table)
    console.print()

    # Print summaries if available (LLM topics have them)
    has_summaries = any(topic.get("summary") for topic in topics_sorted)

    if has_summaries:
        console.print("[bold]Summaries:[/bold]")
        console.print()
        for topic in topics_sorted:
            summary = topic.get("summary", "")
            if summary:
                topic_id = topic["topic_id"]
                label = topic.get("label", topic_id)
                console.print(f"[cyan]{topic_id}[/cyan] {label}")
                console.print(f"  [dim]{summary}[/dim]")
                console.print()

    # Summary line
    console.print(f"[dim]Total: {len(topics_sorted)} topics, {format_timestamp(total_duration)}[/dim]")

    return topics_sorted
