"""Video export command for vodtool using ffmpeg."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()
logger = logging.getLogger("vodtool")


def check_ffmpeg_available(ffmpeg_path: str = "ffmpeg") -> bool:
    """Check if ffmpeg is installed and accessible."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def build_ffmpeg_command(
    source_path: Path,
    keep_spans: list[dict],
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """
    Build ffmpeg command for cutting and concatenating spans.

    Args:
        source_path: Path to source video
        keep_spans: List of spans to keep with start/end times
        output_path: Path for output video
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        ffmpeg command as list of arguments
    """
    if not keep_spans:
        raise ValueError("No keep spans provided")

    # Build filter_complex expression
    filter_parts = []
    concat_inputs = []

    for i, span in enumerate(keep_spans):
        start = span["start"]
        end = span["end"]

        # Trim video and audio streams
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")

        concat_inputs.append(f"[v{i}][a{i}]")

    # Concatenate all segments
    n = len(keep_spans)
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]")

    filter_complex = ";".join(filter_parts)

    # Build full command
    return [
        ffmpeg_path,
        "-i",
        str(source_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",  # H.264 codec
        "-preset",
        "medium",  # Balance speed/quality
        "-crf",
        "23",  # Quality (lower = better, 23 is default)
        "-c:a",
        "aac",  # AAC audio
        "-b:a",
        "128k",  # Audio bitrate
        "-y",  # Overwrite output
        str(output_path),
    ]


def create_export_index(keep_spans: list[dict], chunks_data: list[dict]) -> dict:
    """
    Create time index mapping from original to export video.

    Args:
        keep_spans: List of spans that were kept
        chunks_data: All chunks with IDs and times

    Returns:
        Export index dictionary
    """
    # Build original_to_export mapping
    original_to_export = []
    export_time = 0.0

    for span in keep_spans:
        original_to_export.append(
            {
                "original_start": span["start"],
                "original_end": span["end"],
                "export_start": export_time,
            },
        )
        export_time += span["end"] - span["start"]

    # Build chunk_export_times mapping
    chunk_times = {}

    for chunk in chunks_data:
        chunk_id = chunk["id"]
        chunk_start = chunk["start"]

        # Find which keep span (if any) contains this chunk
        for mapping in original_to_export:
            if mapping["original_start"] <= chunk_start < mapping["original_end"]:
                # Calculate export time
                offset = chunk_start - mapping["original_start"]
                export_time = mapping["export_start"] + offset
                chunk_times[chunk_id] = export_time
                break

    return {
        "original_to_export": original_to_export,
        "chunk_export_times": chunk_times,
    }


def create_preview_html(project_path: Path, keep_spans: list[dict], export_index: dict) -> str:
    """
    Create HTML preview player with clickable timestamps.

    Args:
        project_path: Path to project directory
        keep_spans: List of spans that were kept
        export_index: Export index with time mappings

    Returns:
        HTML content as string
    """
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VodTool Export Preview</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }
        h1 {
            color: #4a9eff;
        }
        video {
            width: 100%;
            border-radius: 8px;
            background: #000;
        }
        .spans {
            margin-top: 20px;
        }
        .span {
            padding: 10px;
            margin: 5px 0;
            background: #2a2a2a;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .span:hover {
            background: #3a3a3a;
        }
        .span-time {
            color: #4a9eff;
            font-weight: bold;
        }
        .span-duration {
            color: #888;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <h1>VodTool Export Preview</h1>

    <video id="player" controls>
        <source src="export.mp4" type="video/mp4">
        Your browser does not support the video tag.
    </video>

    <div class="spans">
        <h2>Export Spans</h2>
"""

    # Add clickable spans
    for i, span in enumerate(keep_spans):
        mapping = export_index["original_to_export"][i]
        export_start = mapping["export_start"]
        duration = span["end"] - span["start"]

        html += f"""        <div class="span" onclick="seekTo({export_start})">
            <span class="span-time">Span {i+1}: {format_time(export_start)}</span>
            <span class="span-duration">({format_time(duration)})</span>
        </div>
"""

    html += """    </div>

    <script>
        const player = document.getElementById('player');

        function seekTo(time) {
            player.currentTime = time;
            player.play();
        }
    </script>
</body>
</html>
"""

    return html


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def export_video(project_path: Path, ffmpeg_path: str = "ffmpeg") -> Optional[Path]:
    """
    Export video based on cut plan.

    Args:
        project_path: Path to the project directory
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Path to the export.mp4 file, or None if export failed
    """
    # Check ffmpeg availability
    if not check_ffmpeg_available(ffmpeg_path):
        console.print(
            f"[red]Error: ffmpeg not installed or not accessible at: {ffmpeg_path}[/red]",
        )
        console.print("\nPlease install ffmpeg:")
        console.print("  macOS: brew install ffmpeg")
        console.print("  Ubuntu/Debian: sudo apt-get install ffmpeg")
        console.print("\nOr specify a custom path with --ffmpeg-path")
        return None

    # Validate project directory
    if not project_path.exists():
        console.print(f"[red]Error: Project directory not found: {project_path}[/red]")
        return None

    if not project_path.is_dir():
        console.print(f"[red]Error: Not a directory: {project_path}[/red]")
        return None

    # Check for cutplan.json
    cutplan_path = project_path / "cutplan.json"
    if not cutplan_path.exists():
        console.print(f"[red]Error: Cut plan not found: {cutplan_path}[/red]")
        console.print("Run 'vodtool cutplan' first to generate a cut plan.")
        return None

    # Load cutplan
    console.print("[cyan]Loading cut plan...[/cyan]")

    try:
        with cutplan_path.open(encoding="utf-8") as f:
            cutplan = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading cut plan: {e}[/red]")
        return None

    keep_spans = cutplan.get("keep_spans", [])
    if not keep_spans:
        console.print("[red]Error: No keep spans in cut plan[/red]")
        return None

    logger.info(f"Cut plan has {len(keep_spans)} keep spans")

    # Find source video
    source_files = list(project_path.glob("source.*"))
    if not source_files:
        console.print("[red]Error: Source video not found[/red]")
        return None

    source_path = source_files[0]
    logger.info(f"Source video: {source_path}")

    # Output paths
    export_path = project_path / "export.mp4"
    index_path = project_path / "export_index.json"
    preview_path = project_path / "preview.html"

    # Build ffmpeg command
    console.print("[cyan]Building ffmpeg command...[/cyan]")

    try:
        cmd = build_ffmpeg_command(source_path, keep_spans, export_path, ffmpeg_path)
        logger.debug(f"ffmpeg command: {' '.join(cmd)}")
    except Exception as e:
        console.print(f"[red]Error building ffmpeg command: {e}[/red]")
        return None

    # Execute ffmpeg
    console.print("[cyan]Exporting video...[/cyan]")
    console.print("[dim]This may take a while depending on video length...[/dim]")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug(f"ffmpeg output: {result.stderr}")
    except subprocess.CalledProcessError as e:
        console.print("[red]Error during video export:[/red]")
        console.print(f"[red]{e.stderr}[/red]")
        return None

    if not export_path.exists() or export_path.stat().st_size == 0:
        console.print("[red]Error: Export file is empty or missing[/red]")
        return None

    logger.info(f"Exported video to: {export_path}")

    # Load chunks for export index
    chunks_path = project_path / "chunks.json"
    chunks_data = []

    if chunks_path.exists():
        try:
            with chunks_path.open(encoding="utf-8") as f:
                chunks_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load chunks for index: {e}")

    # Create export index
    console.print("[cyan]Creating export index...[/cyan]")

    try:
        export_index = create_export_index(keep_spans, chunks_data)

        with index_path.open("w", encoding="utf-8") as f:
            json.dump(export_index, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved export index: {index_path}")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create export index: {e}[/yellow]")
        logger.warning(f"Export index creation failed: {e}")

    # Create HTML preview
    console.print("[cyan]Creating HTML preview...[/cyan]")

    try:
        html_content = create_preview_html(project_path, keep_spans, export_index)

        with preview_path.open("w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"Saved preview: {preview_path}")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create preview: {e}[/yellow]")
        logger.warning(f"Preview creation failed: {e}")

    # Print summary
    export_size_mb = export_path.stat().st_size / (1024 * 1024)
    total_duration = sum(s["end"] - s["start"] for s in keep_spans)

    console.print("\n[green]✓ Export complete![/green]")
    console.print(f"[bold]Export video:[/bold] {export_path}")
    console.print(f"[bold]File size:[/bold] {export_size_mb:.1f} MB")
    console.print(f"[bold]Duration:[/bold] {total_duration:.1f}s ({total_duration/60:.1f} min)")
    console.print(f"[bold]Spans:[/bold] {len(keep_spans)}")
    console.print(f"[bold]Preview:[/bold] {preview_path}")
    console.print(f"\n[cyan]Open {preview_path} in a browser to preview the video![/cyan]")

    return export_path
