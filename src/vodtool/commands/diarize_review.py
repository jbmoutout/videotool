"""Speaker review command for reclassifying speakers after diarization."""

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)


def display_speaker_stats(
    diarization_segments: list[dict],
    speaker_map: dict,
) -> dict:
    """
    Display speaker statistics table and return stats dict.

    Args:
        diarization_segments: List of diarization segments
        speaker_map: Current speaker map

    Returns:
        Dict mapping speaker_id to stats
    """
    # Compute stats for each speaker
    speaker_stats = {}

    for seg in diarization_segments:
        speaker_id = seg["speaker_id"]
        duration = seg["end"] - seg["start"]

        if speaker_id not in speaker_stats:
            speaker_stats[speaker_id] = {
                "total_time": 0.0,
                "segment_count": 0,
                "segments": [],
            }

        speaker_stats[speaker_id]["total_time"] += duration
        speaker_stats[speaker_id]["segment_count"] += 1
        speaker_stats[speaker_id]["segments"].append(duration)

    # Calculate avg segment length
    for speaker_id, stats in speaker_stats.items():
        stats["avg_segment_length"] = stats["total_time"] / stats["segment_count"]

    # Build current role mapping
    role_map = {}
    for main_speaker in speaker_map.get("main_speakers", []):
        role_map[main_speaker["speaker_id"]] = main_speaker["role"]
    for bg_speaker in speaker_map.get("background_speakers", []):
        role_map[bg_speaker["speaker_id"]] = "BACKGROUND"
    for other_speaker in speaker_map.get("other_speakers", []):
        role_map[other_speaker["speaker_id"]] = "OTHER"

    # Display table
    table = Table(title="Speaker Statistics")
    table.add_column("Speaker ID", style="cyan")
    table.add_column("Current Role", style="magenta")
    table.add_column("Total Time (s)", justify="right", style="green")
    table.add_column("Segments", justify="right")
    table.add_column("Avg Segment (s)", justify="right")

    # Sort by total time descending
    sorted_speakers = sorted(
        speaker_stats.items(),
        key=lambda x: x[1]["total_time"],
        reverse=True,
    )

    for speaker_id, stats in sorted_speakers:
        current_role = role_map.get(speaker_id, "UNKNOWN")
        table.add_row(
            speaker_id,
            current_role,
            f"{stats['total_time']:.1f}",
            str(stats["segment_count"]),
            f"{stats['avg_segment_length']:.1f}",
        )

    console.print(table)

    return speaker_stats


def prompt_speaker_classification(speaker_map: dict) -> dict:
    """
    Prompt user to classify speakers as BACKGROUND.

    Args:
        speaker_map: Current speaker map

    Returns:
        Updated speaker map
    """
    console.print("\n[bold yellow]Speaker Classification[/bold yellow]")
    console.print("Review the speakers above. Background audio (e.g., video being watched)")
    console.print("should be marked as BACKGROUND to exclude from topic analysis.\n")

    # Get all speakers
    all_speakers = []
    for main_speaker in speaker_map.get("main_speakers", []):
        all_speakers.append(
            {"speaker_id": main_speaker["speaker_id"], "role": main_speaker["role"], "seconds": main_speaker["seconds"]}
        )
    for bg_speaker in speaker_map.get("background_speakers", []):
        all_speakers.append(
            {"speaker_id": bg_speaker["speaker_id"], "role": "BACKGROUND", "seconds": bg_speaker["seconds"]}
        )
    for other_speaker in speaker_map.get("other_speakers", []):
        all_speakers.append(
            {"speaker_id": other_speaker["speaker_id"], "role": "OTHER", "seconds": other_speaker["seconds"]}
        )

    # Prompt for background speakers
    console.print("Enter speaker IDs to mark as BACKGROUND (comma-separated), or press Enter to skip:")
    background_input = console.input("[bold cyan]> [/bold cyan]").strip()

    if not background_input:
        console.print("[dim]No changes made.[/dim]")
        return speaker_map

    # Parse input
    background_ids = {sid.strip() for sid in background_input.split(",")}

    # Reclassify speakers
    new_main_speakers = []
    new_background_speakers = []
    new_other_speakers = []

    for speaker in all_speakers:
        speaker_id = speaker["speaker_id"]

        if speaker_id in background_ids:
            # Mark as background
            new_background_speakers.append(
                {"speaker_id": speaker_id, "seconds": speaker["seconds"]}
            )
            console.print(f"[green]✓[/green] Marked {speaker_id} as BACKGROUND")
        elif speaker.get("role", "").startswith("MAIN_"):
            # Keep as main
            new_main_speakers.append(speaker)
        elif speaker.get("role") == "BACKGROUND":
            # Was background, keep unless reclassified
            new_background_speakers.append(
                {"speaker_id": speaker_id, "seconds": speaker["seconds"]}
            )
        else:
            # Other speakers
            new_other_speakers.append(
                {"speaker_id": speaker_id, "seconds": speaker["seconds"]}
            )

    # Rebuild main speaker roles based on remaining main speakers
    new_main_speakers.sort(key=lambda x: x["seconds"], reverse=True)
    for idx, speaker in enumerate(new_main_speakers):
        speaker["role"] = f"MAIN_{idx + 1}"

    return {
        "num_main": len(new_main_speakers),
        "main_speakers": new_main_speakers,
        "background_speakers": new_background_speakers,
        "other_speakers": new_other_speakers,
    }


def diarize_review_command(project_path: Path = typer.Argument(..., help="Path to project folder")):
    """
    Review and reclassify speakers after diarization.

    Displays speaker statistics and allows marking speakers as
    BACKGROUND (e.g., audio from video being watched). Background
    speakers are excluded from topic analysis like OTHER speakers.
    """
    if not project_path.exists():
        console.print(f"[red]Error: Project path does not exist: {project_path}[/red]")
        raise typer.Exit(1)

    # Check for required files
    diarization_file = project_path / "diarization_segments.json"
    speaker_map_file = project_path / "speaker_map.json"

    if not diarization_file.exists():
        console.print(f"[red]Error: diarization_segments.json not found in {project_path}[/red]")
        console.print("Run 'vodtool diarize' first to generate diarization data.")
        raise typer.Exit(1)

    if not speaker_map_file.exists():
        console.print(f"[red]Error: speaker_map.json not found in {project_path}[/red]")
        console.print("Run 'vodtool diarize' first to generate speaker map.")
        raise typer.Exit(1)

    # Load files
    with diarization_file.open() as f:
        diarization_segments = json.load(f)

    with speaker_map_file.open() as f:
        speaker_map = json.load(f)

    # Ensure background_speakers key exists (backwards compatibility)
    if "background_speakers" not in speaker_map:
        speaker_map["background_speakers"] = []

    # Display speaker stats
    console.print("\n[bold cyan]Reviewing Speaker Diarization[/bold cyan]\n")
    display_speaker_stats(diarization_segments, speaker_map)

    # Prompt for classification
    updated_speaker_map = prompt_speaker_classification(speaker_map)

    # Save updated speaker map
    with speaker_map_file.open("w") as f:
        json.dump(updated_speaker_map, f, indent=2)

    console.print(f"\n[green]✓ Updated speaker map saved to {speaker_map_file}[/green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Re-run 'vodtool chunks' to update chunk speaker labels")
    console.print("  2. Re-run 'vodtool embed' if needed (to update database)")
    console.print("  3. Continue with 'vodtool segment-topics' and 'vodtool topics'")
