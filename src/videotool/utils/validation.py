"""Input validation utilities for videotool."""

import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# Common video file extensions
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ts",
}

# Warning threshold for large files (50GB)
LARGE_FILE_WARNING_BYTES = 50 * 1024 * 1024 * 1024

# Minimum free space required (5GB safety margin)
MIN_FREE_SPACE_BYTES = 5 * 1024 * 1024 * 1024


def validate_video_file(file_path: Path) -> Optional[str]:
    """
    Validate that a file exists, is a file, and appears to be a video.

    Args:
        file_path: Path to validate

    Returns:
        Error message if validation fails, None if valid
    """
    if not file_path.exists():
        return f"File not found: {file_path}"

    if not file_path.is_file():
        return f"Not a file: {file_path}"

    # Check extension (permissive - ffmpeg supports many formats)
    if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
        return (
            f"Unsupported file extension: {file_path.suffix}\n"
            f"Expected video file ({', '.join(sorted(VIDEO_EXTENSIONS))})"
        )

    return None


def check_file_size(file_path: Path) -> Optional[str]:
    """
    Check if file is very large and warn user.

    Args:
        file_path: Path to check

    Returns:
        Warning message if file is large, None otherwise
    """
    try:
        size_bytes = file_path.stat().st_size
        if size_bytes > LARGE_FILE_WARNING_BYTES:
            size_gb = size_bytes / (1024 * 1024 * 1024)
            return (
                f"Large file detected: {size_gb:.1f}GB\n"
                f"Processing may take significant time and disk space."
            )
    except OSError:
        # If we can't stat the file, skip the warning
        pass

    return None


def check_disk_space(target_dir: Path, required_bytes: int) -> Optional[str]:
    """
    Check if target directory has enough free space.

    Args:
        target_dir: Directory where files will be written
        required_bytes: Minimum bytes required

    Returns:
        Error message if insufficient space, None if sufficient
    """
    try:
        # Get disk usage for target directory's filesystem
        stat = shutil.disk_usage(target_dir)
        free_bytes = stat.free

        # Require file size + MIN_FREE_SPACE_BYTES safety margin
        needed = required_bytes + MIN_FREE_SPACE_BYTES

        if free_bytes < needed:
            free_gb = free_bytes / (1024 * 1024 * 1024)
            needed_gb = needed / (1024 * 1024 * 1024)
            return (
                f"Insufficient disk space: {free_gb:.1f}GB free, {needed_gb:.1f}GB required\n"
                f"(includes 5GB safety margin)"
            )

    except OSError as e:
        # If we can't check disk space, warn but don't fail
        console.print(f"[yellow]Warning: Could not check disk space: {e}[/yellow]")

    return None


def validate_project_path(project_path: Path) -> Optional[str]:
    """
    Validate that a path points to a valid videotool project.

    Args:
        project_path: Path to validate

    Returns:
        Error message if validation fails, None if valid
    """
    if not project_path.exists():
        return f"Project directory not found: {project_path}"

    if not project_path.is_dir():
        return f"Not a directory: {project_path}"

    # Check for required project files
    meta_path = project_path / "meta.json"
    if not meta_path.exists():
        return f"Not a valid videotool project (missing meta.json): {project_path}"

    return None


def get_projects_dir() -> Path:
    """
    Get the videotool projects directory.

    Returns ~/.videotool/projects, creating it if needed.

    Returns:
        Path to projects directory
    """
    projects_dir = Path.home() / ".videotool" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir
