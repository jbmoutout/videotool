"""Video ingestion command for vodtool."""

import json
import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.validation import (
    check_disk_space,
    check_file_size,
    get_projects_dir,
    validate_video_file,
)

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


def get_ffprobe_path(ffmpeg_path: str) -> str:
    """
    Derive ffprobe path from ffmpeg path.

    Handles both simple names ('ffmpeg') and full paths ('/usr/local/bin/ffmpeg-custom').

    Args:
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Path to ffprobe binary
    """
    ffmpeg = Path(ffmpeg_path)
    # If it's just 'ffmpeg', return 'ffprobe'
    if ffmpeg.name == "ffmpeg":
        return "ffprobe"
    # Otherwise, same directory, replace 'ffmpeg' with 'ffprobe' in the name
    probe_name = ffmpeg.name.replace("ffmpeg", "ffprobe")
    return str(ffmpeg.parent / probe_name)


def get_video_duration(video_path: Path, ffprobe_path: str = "ffprobe") -> Optional[float]:
    """
    Extract video duration using ffprobe.

    Returns duration in seconds, or None if extraction fails.
    """
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,  # Prevent hanging on corrupted files
        )
        duration_str = result.stdout.strip()
        if duration_str:
            return float(duration_str)
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe timed out after 30s on {video_path}")
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        logger.warning(f"Could not extract video duration: {e}")
    return None


def extract_audio(video_path: Path, output_path: Path, ffmpeg_path: str = "ffmpeg") -> bool:
    """
    Extract audio from video as mono 16kHz WAV.

    Args:
        video_path: Path to source video file
        output_path: Path for output audio.wav file
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-i",
                str(video_path),
                "-ac",
                "1",  # mono
                "-ar",
                "16000",  # 16kHz sample rate
                "-y",  # overwrite output
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug(f"ffmpeg output: {result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed: {e.stderr}")
        return False


def ingest_video(input_video_path: Path, ffmpeg_path: str = "ffmpeg") -> Optional[Path]:
    """
    Ingest a video file and create a new project.

    Args:
        input_video_path: Path to the input video file
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Path to the created project directory, or None if ingestion failed
    """
    # Derive ffprobe path from ffmpeg path
    ffprobe_path = get_ffprobe_path(ffmpeg_path)

    # Check ffmpeg availability
    if not check_ffmpeg_available(ffmpeg_path):
        console.print(
            f"[red]Error: ffmpeg not installed or not accessible at: {ffmpeg_path}[/red]",
        )
        console.print("\nPlease install ffmpeg:")
        console.print("  macOS: brew install ffmpeg")
        console.print("  Ubuntu/Debian: sudo apt-get install ffmpeg")
        console.print("  Other: https://ffmpeg.org/download.html")
        console.print("\nOr specify a custom path with --ffmpeg-path")
        return None

    # Validate input file (file exists, is a file, has video extension)
    error = validate_video_file(input_video_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Warn about large files
    warning = check_file_size(input_video_path)
    if warning:
        console.print(f"[yellow]Warning: {warning}[/yellow]")

    # Get file size for disk space check
    try:
        file_size = input_video_path.stat().st_size
    except OSError as e:
        console.print(f"[red]Error: Cannot access file: {e}[/red]")
        return None

    # Generate project ID
    project_id = uuid.uuid4().hex[:8]
    logger.info(f"Creating project with ID: {project_id}")

    # Get projects directory (uses ~/.vodtool/projects)
    projects_dir = get_projects_dir()

    # Check disk space before creating project
    # Need space for: source copy + audio.wav (~10% of source) + safety margin
    required_space = int(file_size * 1.2)  # 20% overhead for audio + temp files
    error = check_disk_space(projects_dir, required_space)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    project_dir = projects_dir / project_id
    if project_dir.exists():
        console.print(f"[red]Error: Project directory already exists: {project_dir}[/red]")
        return None

    try:
        project_dir.mkdir(parents=True)
        logger.info(f"Created project directory: {project_dir}")
    except OSError as e:
        console.print(f"[red]Error: Cannot create project directory: {e}[/red]")
        return None

    # Copy source video
    source_extension = input_video_path.suffix
    source_filename = f"source{source_extension}"
    source_path = project_dir / source_filename

    console.print("[cyan]Copying source video...[/cyan]")
    try:
        shutil.copy2(input_video_path, source_path)
        logger.info(f"Copied source video to: {source_path}")
    except (OSError, IOError, shutil.Error) as e:
        console.print(f"[red]Error copying video: {e}[/red]")
        console.print("[dim]Cleaning up project directory...[/dim]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    # Extract video duration
    console.print("[cyan]Extracting metadata...[/cyan]")
    duration = get_video_duration(source_path, ffprobe_path)
    if duration:
        logger.info(f"Video duration: {duration:.2f} seconds")

    # Extract audio
    audio_path = project_dir / "audio.wav"
    console.print("[cyan]Extracting audio (mono, 16kHz)...[/cyan]")

    if not extract_audio(source_path, audio_path, ffmpeg_path):
        console.print("[red]Error: Audio extraction failed[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        console.print("[red]Error: Audio file is empty or missing[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    logger.info(f"Extracted audio to: {audio_path}")

    # Create metadata
    metadata = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": input_video_path.name,
        "source_path": str(input_video_path.absolute()),
        "duration_seconds": duration,
        "audio_path": "audio.wav",
    }

    meta_path = project_dir / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logger.info(f"Created metadata: {meta_path}")

    console.print("\n[green]✓ Project created successfully![/green]")
    console.print(f"[bold]Project path:[/bold] {project_dir.absolute()}")
    if duration:
        console.print(f"[dim]Duration: {duration:.1f}s ({duration/60:.1f} min)[/dim]")

    return project_dir
