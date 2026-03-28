"""Video ingestion command for vodtool."""

import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.twitch import (
    check_streamlink,
    download_chat,
    download_vod,
    is_twitch_url,
    parse_twitch_video_id,
)
from vodtool.utils.validation import (
    check_disk_space,
    check_file_size,
    get_projects_dir,
    validate_video_file,
)

console = Console()
logger = logging.getLogger("vodtool")

# Last error message from ingest_video — readable by pipeline after a None return.
_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by ingest_video."""
    return _last_error


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


def extract_audio(
    video_path: Path,
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
    duration: Optional[float] = None,
    progress_callback=None,
) -> bool:
    """
    Extract audio from video as mono 16kHz WAV.

    Args:
        video_path: Path to source video file
        output_path: Path for output audio.wav file
        ffmpeg_path: Path to ffmpeg binary
        duration: Known video duration in seconds (for progress %)
        progress_callback: Optional callable(pct: float) called with 0.0-1.0

    Returns:
        True if successful, False otherwise
    """
    import re as _re

    cmd = [
        ffmpeg_path,
        "-i",
        str(video_path),
        "-ac",
        "1",  # mono
        "-ar",
        "16000",  # 16kHz sample rate
        "-y",  # overwrite output
    ]
    if progress_callback and duration and duration > 0:
        # -progress pipe:1 makes ffmpeg write progress to stdout
        cmd.extend(["-progress", "pipe:1"])
    cmd.append(str(output_path))

    if not progress_callback or not duration or duration <= 0:
        # Simple mode: no progress tracking
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"ffmpeg output: {result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg failed: {e.stderr}")
            return False

    # Progress mode: parse ffmpeg's -progress output
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        for line in proc.stdout:
            line = line.strip()
            # ffmpeg -progress outputs lines like: out_time_us=12345678
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=")[1])
                    secs = us / 1_000_000
                    pct = min(secs / duration, 0.99)
                    progress_callback(pct)
                except (ValueError, ZeroDivisionError):
                    pass

        proc.wait()
        if proc.returncode != 0:
            logger.error("ffmpeg failed during audio extraction")
            return False

        progress_callback(1.0)
        return True

    except Exception as e:
        logger.error(f"ffmpeg failed: {e}")
        return False


def ingest_video(
    input_video_path,
    ffmpeg_path: str = "ffmpeg",
    quality: str = "worst",
    download_progress_callback=None,
    status_callback=None,
) -> Optional[Path]:
    """
    Ingest a video file or Twitch VOD URL and create a new project.

    Args:
        input_video_path: Path to a local video file, or a Twitch VOD URL
        ffmpeg_path: Path to ffmpeg binary
        quality: streamlink quality for Twitch downloads (default: 720p,720p60,best)

    Returns:
        Path to the created project directory, or None if ingestion failed
    """
    global _last_error
    _last_error = None
    twitch_url = None

    # Handle Twitch URL input
    if isinstance(input_video_path, str) and is_twitch_url(input_video_path):
        twitch_url = input_video_path
        video_id = parse_twitch_video_id(twitch_url)

        if not check_streamlink():
            _last_error = "streamlink not installed. Install with: pip install streamlink"
            console.print("[red]Error: streamlink not installed.[/red]")
            console.print("Install it with: [bold]pip install streamlink[/bold]")
            return None

        console.print(f"[cyan]Twitch VOD detected: video {video_id}[/cyan]")
        console.print("[cyan]Downloading VOD (this may take a while)...[/cyan]")

        tmp_dir = tempfile.mkdtemp(prefix="vodtool_twitch_")
        tmp_video = Path(tmp_dir) / "vod.mp4"

        if download_progress_callback:
            from vodtool.utils.twitch import download_vod_with_progress

            success = download_vod_with_progress(
                twitch_url,
                tmp_video,
                quality=quality,
                progress_callback=download_progress_callback,
            )
        else:
            success = download_vod(twitch_url, tmp_video, quality=quality)
        if not success:
            _last_error = "Twitch VOD download failed"
            console.print("[red]Error: VOD download failed.[/red]")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        input_video_path = tmp_video

    else:
        if isinstance(input_video_path, str):
            input_video_path = Path(input_video_path)
        tmp_dir = None
        video_id = None

    # Derive ffprobe path from ffmpeg path
    ffprobe_path = get_ffprobe_path(ffmpeg_path)

    # Check ffmpeg availability
    if not check_ffmpeg_available(ffmpeg_path):
        _last_error = f"ffmpeg not found at: {ffmpeg_path}. Install with: brew install ffmpeg"
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
        _last_error = error
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
        _last_error = f"Cannot access file: {e}"
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
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    project_dir = projects_dir / project_id
    if project_dir.exists():
        _last_error = f"Project directory already exists: {project_dir}"
        console.print(f"[red]Error: Project directory already exists: {project_dir}[/red]")
        return None

    try:
        project_dir.mkdir(parents=True)
        logger.info(f"Created project directory: {project_dir}")
    except OSError as e:
        _last_error = f"Cannot create project directory: {e}"
        console.print(f"[red]Error: Cannot create project directory: {e}[/red]")
        return None

    # Move or link source video (avoid duplicating multi-GB files)
    source_path = project_dir / "source.mp4"

    try:
        if tmp_dir:
            # Twitch download: streamlink outputs raw MPEG-TS (HLS segments).
            # Browsers can't play TS natively, so remux to proper MP4.
            console.print("[cyan]Remuxing to MP4...[/cyan]")
            remuxed_path = project_dir / "source.mp4"
            remux_result = subprocess.run(
                [
                    ffmpeg_path,
                    "-i",
                    str(input_video_path),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-y",
                    str(remuxed_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if remux_result.returncode != 0:
                logger.error(f"ffmpeg remux failed: {remux_result.stderr}")
                _last_error = "Video remux to MP4 failed"
                console.print("[red]Error: Video remux failed[/red]")
                shutil.rmtree(project_dir, ignore_errors=True)
                return None
            source_path = remuxed_path
        else:
            # Local file: hardlink to avoid duplicating multi-GB files.
            # Hardlinks survive if the original path is renamed/moved (unlike symlinks).
            # Falls back to symlink if hardlink fails (cross-device or unsupported FS).
            source_extension = input_video_path.suffix
            source_filename = f"source{source_extension}"
            source_path = project_dir / source_filename
            console.print("[cyan]Linking source video...[/cyan]")
            try:
                source_path.hardlink_to(input_video_path.resolve())
            except (OSError, NotImplementedError):
                source_path.symlink_to(input_video_path.resolve())
        logger.info(f"Source video at: {source_path}")
    except (OSError, IOError, shutil.Error) as e:
        _last_error = f"Failed to set up video: {e}"
        console.print(f"[red]Error setting up video: {e}[/red]")
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
    if status_callback:
        status_callback("extracting audio...")

    def _audio_progress(pct: float):
        if status_callback:
            status_callback(f"extracting audio: {int(pct * 100)}%")

    if not extract_audio(
        source_path,
        audio_path,
        ffmpeg_path,
        duration=duration,
        progress_callback=_audio_progress if status_callback else None,
    ):
        _last_error = "Audio extraction failed"
        console.print("[red]Error: Audio extraction failed[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        _last_error = "Audio file is empty or missing after extraction"
        console.print("[red]Error: Audio file is empty or missing[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    logger.info(f"Extracted audio to: {audio_path}")

    # Download chat replay for Twitch VODs
    if twitch_url and video_id:
        console.print("[cyan]Downloading chat replay...[/cyan]")
        chat_path = project_dir / "chat.json"
        ok = download_chat(video_id, chat_path)
        if ok:
            msg_count = len(json.loads(chat_path.read_text()))
            console.print(f"[dim]Chat: {msg_count} messages saved[/dim]")
        else:
            console.print(
                "[yellow]Warning: Chat download failed — continuing without chat[/yellow]"
            )

    # Clean up temp download dir
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Create metadata
    metadata = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": twitch_url or input_video_path.name,
        "source_path": twitch_url or str(input_video_path.absolute()),
        "duration_seconds": duration,
        "audio_path": "audio.wav",
        **({"twitch_video_id": video_id, "twitch_url": twitch_url} if twitch_url else {}),
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
