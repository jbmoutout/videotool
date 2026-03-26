"""Tests for vodtool.utils.file_utils module."""

import fcntl
import json
from pathlib import Path

import pytest

from vodtool.utils.file_utils import (
    project_lock,
    safe_read_json,
    safe_write_json,
    validate_json_files,
)


class TestSafeReadJson:
    """Tests for safe_read_json()."""

    def test_reads_valid_json(self, mock_json_file):
        """Successfully reads valid JSON file."""
        data = safe_read_json(mock_json_file)
        assert data is not None
        assert data["test"] == "data"
        assert data["numbers"] == [1, 2, 3]

    def test_returns_none_for_missing_file(self, temp_dir):
        """Returns None for non-existent file."""
        missing_file = temp_dir / "missing.json"
        data = safe_read_json(missing_file)
        assert data is None

    def test_returns_none_for_corrupted_json(self, corrupted_json_file):
        """Returns None for invalid JSON."""
        data = safe_read_json(corrupted_json_file)
        assert data is None

    def test_returns_none_for_empty_file(self, temp_dir):
        """Returns None for empty JSON file."""
        empty_file = temp_dir / "empty.json"
        empty_file.write_text("")
        data = safe_read_json(empty_file)
        assert data is None


class TestSafeWriteJson:
    """Tests for safe_write_json()."""

    def test_writes_json_successfully(self, temp_dir):
        """Successfully writes JSON data."""
        output_file = temp_dir / "output.json"
        test_data = {"key": "value", "numbers": [1, 2, 3]}

        result = safe_write_json(output_file, test_data)
        assert result is True
        assert output_file.exists()

        # Verify content
        with output_file.open() as f:
            loaded = json.load(f)
        assert loaded == test_data

    def test_atomic_write_with_temp_file(self, temp_dir):
        """Uses temp file for atomic write (temp file cleaned up)."""
        output_file = temp_dir / "output.json"
        test_data = {"test": "atomic"}

        safe_write_json(output_file, test_data)

        # Temp file should not exist after write
        temp_file = temp_dir / "output.tmp"
        assert not temp_file.exists()

    def test_overwrites_existing_file(self, temp_dir):
        """Overwrites existing file atomically."""
        output_file = temp_dir / "output.json"

        # Write initial data
        safe_write_json(output_file, {"version": 1})
        assert safe_read_json(output_file)["version"] == 1

        # Overwrite with new data
        safe_write_json(output_file, {"version": 2})
        assert safe_read_json(output_file)["version"] == 2

    def test_returns_false_on_error(self, temp_dir):
        """Returns False when write fails."""
        # Try to write to a read-only directory
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        output_file = readonly_dir / "output.json"
        result = safe_write_json(output_file, {"test": "data"})

        assert result is False
        # Cleanup
        readonly_dir.chmod(0o755)


class TestProjectLock:
    """Tests for project_lock() context manager."""

    def test_acquires_and_releases_lock(self, mock_project_dir):
        """Successfully acquires and releases lock."""
        lock_file = mock_project_dir / ".vodtool.lock"

        with project_lock(mock_project_dir):
            # Lock file should exist while locked
            assert lock_file.exists()

        # Lock file should be cleaned up after release
        assert not lock_file.exists()

    def test_prevents_concurrent_access(self, mock_project_dir):
        """Prevents concurrent access by raising BlockingIOError on second lock attempt."""
        import fcntl

        # First lock acquisition succeeds
        with project_lock(mock_project_dir):
            lock_file = mock_project_dir / ".vodtool.lock"
            assert lock_file.exists()

            # Try to acquire lock again in same process (should fail immediately)
            with pytest.raises(BlockingIOError):
                with project_lock(mock_project_dir, timeout=1):
                    pass

    def test_timeout_raises_error(self, mock_project_dir):
        """Raises BlockingIOError when lock cannot be acquired within timeout."""
        # Create a lock file manually to simulate an external lock
        lock_file = mock_project_dir / ".vodtool.lock"

        # Hold the lock in the outer context
        with lock_file.open("w") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            # Now try to acquire the lock with a short timeout
            # This should fail because the file is already locked
            with pytest.raises(BlockingIOError):
                with project_lock(mock_project_dir, timeout=1):
                    pass

    def test_lock_released_on_exception(self, mock_project_dir):
        """Lock is released even if exception occurs within context."""
        lock_file = mock_project_dir / ".vodtool.lock"

        with pytest.raises(ValueError):
            with project_lock(mock_project_dir):
                raise ValueError("Test exception")

        # Lock should be released despite exception
        assert not lock_file.exists()


class TestValidateJsonFiles:
    """Tests for validate_json_files()."""

    def test_all_valid_files_returns_true(self, mock_json_file, temp_dir):
        """Returns True when all files are valid."""
        file2 = temp_dir / "file2.json"
        safe_write_json(file2, {"test": "data2"})

        result = validate_json_files(mock_json_file, file2)
        assert result is True

    def test_corrupted_file_returns_false(self, mock_json_file, corrupted_json_file):
        """Returns False when any file is corrupted."""
        result = validate_json_files(mock_json_file, corrupted_json_file)
        assert result is False

    def test_missing_file_returns_false(self, mock_json_file, temp_dir):
        """Returns False when any file is missing."""
        missing_file = temp_dir / "missing.json"
        result = validate_json_files(mock_json_file, missing_file)
        assert result is False
