"""Video ingestion command for vodtool."""

import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.twitch import (
    check_streamlink,
    download_chat,
    download_vod_with_progress,
    fetch_vod_metadata,
    get_available_streams,
    is_twitch_url,
    parse_twitch_video_id,
    resolve_quality,
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

    For Twitch URLs: downloads a single stream (default: worst/160p),
    remuxes to MP4, and extracts audio for transcription.

    For local files: links source and extracts audio.wav.

    Args:
        input_video_path: Path to a local video file, or a Twitch VOD URL
        ffmpeg_path: Path to ffmpeg binary
        quality: streamlink quality for Twitch downloads (default: worst)
        download_progress_callback: Optional callable(pct: float) for download progress
        status_callback: Optional callable(msg: str) for status messages

    Returns:
        project_dir Path on success, or None if ingestion failed.
        The project contains source.mp4 (video) and audio.wav (for transcription).
    """
    global _last_error
    _last_error = None

    if isinstance(input_video_path, str) and is_twitch_url(input_video_path):
        return _ingest_twitch(
            input_video_path, ffmpeg_path, quality,
            download_progress_callback, status_callback,
        )
    else:
        return _ingest_local(input_video_path, ffmpeg_path, status_callback)


def _ingest_twitch(
    twitch_url: str,
    ffmpeg_path: str,
    video_quality: str,
    download_progress_callback,
    status_callback,
) -> Optional[Path]:
    """Ingest a Twitch VOD: download single stream, remux to MP4, extract audio."""
    global _last_error

    video_id = parse_twitch_video_id(twitch_url)

    if not check_streamlink():
        _last_error = "streamlink not installed. Install with: pip install streamlink"
        console.print("[red]Error: streamlink not installed.[/red]")
        console.print("Install it with: [bold]pip install streamlink[/bold]")
        return None

    if not check_ffmpeg_available(ffmpeg_path):
        _last_error = f"ffmpeg not found at: {ffmpeg_path}. Install with: brew install ffmpeg"
        console.print(f"[red]Error: ffmpeg not found at: {ffmpeg_path}[/red]")
        return None

    # Generate project
    project_id = uuid.uuid4().hex[:8]
    projects_dir = get_projects_dir()
    project_dir = projects_dir / project_id

    try:
        project_dir.mkdir(parents=True)
        logger.info(f"Created project directory: {project_dir}")
    except OSError as e:
        _last_error = f"Cannot create project directory: {e}"
        console.print(f"[red]Error: Cannot create project directory: {e}[/red]")
        return None

    # --- Resolve available quality ---
    console.print(f"[cyan]Twitch VOD detected: video {video_id}[/cyan]")
    if status_callback:
        status_callback("Checking available streams...")

    # Run stream query in a thread so we can emit progress ticks
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(get_available_streams, twitch_url)
        while not future.done():
            import time as _time
            _time.sleep(2)
            if status_callback:
                status_callback("Checking available streams...")
        streams = future.result()

    if streams:
        resolved_quality = resolve_quality(video_quality, streams)
        logger.info(f"Available streams: {streams}")
    else:
        resolved_quality = video_quality
        logger.warning("Could not query streams, using default quality")

    # --- Download single stream (blocking, with progress) ---
    if status_callback:
        status_callback("Downloading video stream...")
    console.print(f"[cyan]Downloading stream (quality: {resolved_quality})...[/cyan]")

    source_ts_path = project_dir / "source.ts"
    if download_progress_callback:
        download_ok = download_vod_with_progress(
            twitch_url, source_ts_path, quality=resolved_quality,
            progress_callback=download_progress_callback,
        )
    else:
        from vodtool.utils.twitch import download_vod
        download_ok = download_vod(twitch_url, source_ts_path, quality=resolved_quality)

    if not download_ok:
        _last_error = "Twitch VOD download failed"
        console.print("[red]Error: VOD download failed.[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    size_mb = source_ts_path.stat().st_size / 1024 / 1024
    logger.info(f"Stream downloaded: {source_ts_path} ({size_mb:.0f}MB)")

    # --- Remux TS → MP4 ---
    if status_callback:
        status_callback("Remuxing video...")
    console.print("[cyan]Remuxing TS → MP4...[/cyan]")

    source_mp4_path = project_dir / "source.mp4"
    remux_result = subprocess.run(
        [ffmpeg_path, "-i", str(source_ts_path),
         "-c", "copy", "-y", str(source_mp4_path)],
        capture_output=True, text=True, check=False,
    )

    if remux_result.returncode == 0 and source_mp4_path.exists():
        source_ts_path.unlink()
        source_path = source_mp4_path
        logger.info(f"Remuxed to: {source_mp4_path}")
    else:
        logger.warning(f"Remux failed (exit {remux_result.returncode}), keeping source.ts")
        source_path = source_ts_path

    # --- Extract audio ---
    if status_callback:
        status_callback("Extracting audio...")
    console.print("[cyan]Extracting audio (mono, 16kHz)...[/cyan]")

    ffprobe_path = get_ffprobe_path(ffmpeg_path)
    duration = get_video_duration(source_path, ffprobe_path)

    audio_path = project_dir / "audio.wav"
    if not extract_audio(source_path, audio_path, ffmpeg_path):
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

    # --- Fetch VOD metadata (title, language) ---
    vod_title = None
    vod_language = None
    vod_channel = None
    if video_id:
        vod_meta = fetch_vod_metadata(video_id)
        if vod_meta:
            vod_title = vod_meta.get("title")
            vod_language = vod_meta.get("language")
            vod_channel = vod_meta.get("channel")
            if vod_title:
                console.print(f"[dim]Title: {vod_title}[/dim]")
            if vod_channel:
                console.print(f"[dim]Channel: {vod_channel}[/dim]")
            if vod_language:
                console.print(f"[dim]Language: {vod_language}[/dim]")

    # --- Download chat replay ---
    if video_id:
        chat_path = project_dir / "chat.json"
        ok = download_chat(video_id, chat_path)
        if ok:
            msg_count = len(json.loads(chat_path.read_text()))
            console.print(f"[dim]Chat: {msg_count} messages saved[/dim]")
        else:
            console.print(
                "[yellow]Warning: Chat download failed — continuing without chat[/yellow]"
            )

    # --- Write metadata ---
    metadata = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": twitch_url,
        "source_path": twitch_url,
        "duration_seconds": duration,
        "audio_path": "audio.wav",
        "twitch_video_id": video_id,
        "twitch_url": twitch_url,
    }
    if vod_title:
        metadata["title"] = vod_title
    if vod_language:
        metadata["language"] = vod_language
    if vod_channel:
        metadata["channel"] = vod_channel
    meta_path = project_dir / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    console.print("\n[green]✓ Project created successfully![/green]")
    console.print(f"[bold]Project path:[/bold] {project_dir.absolute()}")
    if duration:
        console.print(f"[dim]Duration: {duration:.1f}s ({duration/60:.1f} min)[/dim]")

    return project_dir


def _ingest_local(
    input_video_path,
    ffmpeg_path: str,
    status_callback,
) -> Optional[Path]:
    """Ingest a local video file (original flow)."""
    global _last_error

    if isinstance(input_video_path, str):
        input_video_path = Path(input_video_path)

    ffprobe_path = get_ffprobe_path(ffmpeg_path)

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

    error = validate_video_file(input_video_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    warning = check_file_size(input_video_path)
    if warning:
        console.print(f"[yellow]Warning: {warning}[/yellow]")

    try:
        file_size = input_video_path.stat().st_size
    except OSError as e:
        _last_error = f"Cannot access file: {e}"
        console.print(f"[red]Error: Cannot access file: {e}[/red]")
        return None

    project_id = uuid.uuid4().hex[:8]
    logger.info(f"Creating project with ID: {project_id}")
    projects_dir = get_projects_dir()

    required_space = int(file_size * 1.2)
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

    # Link source video
    source_extension = input_video_path.suffix
    source_filename = f"source{source_extension}"
    source_path = project_dir / source_filename
    try:
        console.print("[cyan]Linking source video...[/cyan]")
        try:
            os.link(str(input_video_path.resolve()), str(source_path))
        except (OSError, NotImplementedError):
            source_path.symlink_to(input_video_path.resolve())
        logger.info(f"Source video at: {source_path}")
    except (OSError, IOError, shutil.Error) as e:
        _last_error = f"Failed to set up video: {e}"
        console.print(f"[red]Error setting up video: {e}[/red]")
        shutil.rmtree(project_dir, ignore_errors=True)
        return None

    # Extract duration
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
        source_path, audio_path, ffmpeg_path,
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

    # Write metadata
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
