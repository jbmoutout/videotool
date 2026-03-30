"""Merge two topics into one in the topic map."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from videotool.utils.file_utils import safe_read_json, safe_write_json
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")

_SOURCE_FILES = {
    "llm": "topic_map_llm.json",
    "labeled": "topic_map_labeled.json",
    "basic": "topic_map.json",
}


def _detect_source(project_path: Path) -> Optional[tuple[str, Path]]:
    """Return (source_name, path) for the best available topic map."""
    for name, filename in _SOURCE_FILES.items():
        path = project_path / filename
        if path.exists():
            return name, path
    return None


def merge_topics_command(
    project_path: Path,
    topic_a: str,
    topic_b: str,
    source: str = "auto",
) -> Optional[Path]:
    """
    Merge topic_b into topic_a, combining chunks and spans.

    Args:
        project_path: Path to the project directory
        topic_a: ID of the topic to keep (e.g. 'topic_0002')
        topic_b: ID of the topic to absorb (e.g. 'topic_0003')
        source: Topic map source ('llm', 'labeled', 'basic', or 'auto')

    Returns:
        Path to the updated topic map file, or None on failure
    """
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Resolve source file
    if source == "auto":
        result = _detect_source(project_path)
        if result is None:
            console.print("[red]Error: No topic map found. Run llm-topics first.[/red]")
            return None
        source_name, map_path = result
    else:
        if source not in _SOURCE_FILES:
            console.print(f"[red]Error: Unknown source '{source}'. Use: llm, labeled, basic, auto[/red]")
            return None
        map_path = project_path / _SOURCE_FILES[source]
        source_name = source
        if not map_path.exists():
            console.print(f"[red]Error: {map_path.name} not found.[/red]")
            return None

    topic_map = safe_read_json(map_path)
    if topic_map is None:
        return None

    # Find both topics
    by_id = {t["topic_id"]: t for t in topic_map}

    if topic_a not in by_id:
        console.print(f"[red]Error: topic '{topic_a}' not found.[/red]")
        return None
    if topic_b not in by_id:
        console.print(f"[red]Error: topic '{topic_b}' not found.[/red]")
        return None

    a = by_id[topic_a]
    b = by_id[topic_b]

    # Merge chunks
    merged_chunk_ids = a["chunk_ids"] + [
        c for c in b["chunk_ids"] if c not in a["chunk_ids"]
    ]

    # Merge spans (combine and sort by start time)
    merged_spans = sorted(a["spans"] + b["spans"], key=lambda s: s["start"])

    # Recompute duration
    merged_duration = a["duration_seconds"] + b["duration_seconds"]

    def fmt_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"

    # Build merged topic (keep topic_a's id and label, combine everything)
    merged = {
        **a,
        "chunk_ids": merged_chunk_ids,
        "spans": merged_spans,
        "duration_seconds": merged_duration,
        "duration_label": fmt_duration(merged_duration),
        "chunk_count": len(merged_chunk_ids),
    }

    # Rebuild map: replace topic_a with merged, remove topic_b, renumber
    new_map = []
    for t in topic_map:
        if t["topic_id"] == topic_a:
            new_map.append(merged)
        elif t["topic_id"] == topic_b:
            continue  # drop
        else:
            new_map.append(t)

    # Renumber topic IDs sequentially
    for i, t in enumerate(new_map):
        t["topic_id"] = f"topic_{i:04d}"

    if not safe_write_json(map_path, new_map):
        return None

    console.print(f"[green]✓ Merged '{topic_b}' into '{topic_a}' → saved to {map_path.name}[/green]")
    console.print(f"  New label: [bold]{merged['label']}[/bold]")
    console.print(f"  Duration: {merged['duration_label']} ({merged['chunk_count']} chunks)")
    console.print(f"  Topics remaining: {len(new_map)}")

    return map_path
