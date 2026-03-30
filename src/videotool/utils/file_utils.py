"""File handling utilities for videotool."""

import fcntl
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

console = Console()
logger = logging.getLogger("videotool")


def safe_read_json(file_path: Path) -> Optional[dict[str, Any]]:
    """
    Safely read and parse a JSON file with validation.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data, or None if file doesn't exist/is invalid
    """
    if not file_path.exists():
        logger.debug(f"JSON file not found: {file_path}")
        return None

    if file_path.stat().st_size == 0:
        logger.warning(f"JSON file is empty: {file_path}")
        return None

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {file_path}: {e}")
        console.print(f"[red]Error: Corrupted JSON file: {file_path}[/red]")
        console.print(f"[dim]Parse error: {e}[/dim]")
        return None
    except (OSError, IOError) as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        console.print(f"[red]Error: Cannot read file: {file_path}[/red]")
        console.print(f"[dim]{e}[/dim]")
        return None


def safe_write_json(file_path: Path, data: Any, *, indent: int = 2) -> bool:
    """
    Safely write data to JSON file with atomic write (write to temp, then rename).

    Args:
        file_path: Path to JSON file
        data: Data to serialize
        indent: JSON indentation level

    Returns:
        True if successful, False otherwise
    """
    temp_path = file_path.with_suffix(".tmp")

    try:
        # Write to temporary file first
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)

        # Atomic rename (replaces existing file)
        temp_path.replace(file_path)
        return True

    except (OSError, IOError, TypeError) as e:
        logger.error(f"Failed to write JSON to {file_path}: {e}")
        console.print(f"[red]Error: Cannot write file: {file_path}[/red]")
        console.print(f"[dim]{e}[/dim]")

        # Clean up temp file if it exists (best effort)
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            # Cleanup failed, but write already failed so this is non-critical
            pass

        return False


@contextmanager
def project_lock(project_path: Path, *, timeout: int = 5):
    """
    Acquire an exclusive lock on a videotool project to prevent concurrent access.

    Usage:
        with project_lock(project_path):
            # Do work on project
            pass

    Args:
        project_path: Path to project directory
        timeout: Seconds to wait for lock (default: 5)

    Raises:
        BlockingIOError: If lock cannot be acquired within timeout
        OSError: If lock file cannot be created
    """
    lock_file = project_path / ".videotool.lock"
    lock_fd = None

    try:
        # Create lock file
        lock_fd = lock_file.open("w")

        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            console.print(
                f"[yellow]Warning: Project is locked (another videotool process is using it)[/yellow]"
            )
            console.print(f"[dim]Waiting up to {timeout}s for lock...[/dim]")

            # Try blocking lock with timeout
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("Lock acquisition timed out")

            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                signal.alarm(0)  # Cancel alarm
            except TimeoutError:
                console.print(
                    "[red]Error: Could not acquire project lock (another process is using it)[/red]"
                )
                console.print("[dim]Wait for other process to finish, or remove .videotool.lock file[/dim]")
                raise BlockingIOError(f"Project locked: {project_path}") from None
            finally:
                signal.signal(signal.SIGALRM, old_handler)

        logger.debug(f"Acquired lock on {project_path}")
        yield

    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
                # Clean up lock file
                if lock_file.exists():
                    lock_file.unlink()
                logger.debug(f"Released lock on {project_path}")
            except OSError as e:
                logger.warning(f"Failed to release lock: {e}")


def validate_json_files(*file_paths: Path) -> bool:
    """
    Validate that multiple JSON files exist and are parseable.

    Args:
        file_paths: Paths to JSON files to validate

    Returns:
        True if all files are valid, False otherwise
    """
    all_valid = True

    for file_path in file_paths:
        if safe_read_json(file_path) is None:
            all_valid = False

    return all_valid
