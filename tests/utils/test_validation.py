"""Tests for videotool.utils.validation module."""

from pathlib import Path
from unittest import mock

import pytest

from videotool.utils.validation import (
    check_disk_space,
    check_file_size,
    get_projects_dir,
    validate_project_path,
    validate_video_file,
)


class TestValidateProjectPath:
    """Tests for validate_project_path()."""

    def test_valid_project_returns_none(self, mock_project_dir):
        """Valid project directory with meta.json returns None."""
        error = validate_project_path(mock_project_dir)
        assert error is None

    def test_missing_directory_returns_error(self, temp_dir):
        """Non-existent directory returns error message."""
        missing_path = temp_dir / "nonexistent"
        error = validate_project_path(missing_path)
        assert error is not None
        assert "not found" in error.lower()

    def test_file_not_directory_returns_error(self, mock_json_file):
        """File path (not directory) returns error."""
        error = validate_project_path(mock_json_file)
        assert error is not None
        assert "not a directory" in error.lower()

    def test_missing_meta_json_returns_error(self, temp_dir):
        """Directory without meta.json returns error."""
        empty_dir = temp_dir / "empty_project"
        empty_dir.mkdir()
        error = validate_project_path(empty_dir)
        assert error is not None
        assert "meta.json" in error.lower()


class TestValidateVideoFile:
    """Tests for validate_video_file()."""

    def test_valid_video_file_returns_none(self, mock_video_file):
        """Valid video file with .mp4 extension returns None."""
        error = validate_video_file(mock_video_file)
        assert error is None

    def test_missing_file_returns_error(self, temp_dir):
        """Non-existent file returns error."""
        missing_file = temp_dir / "missing.mp4"
        error = validate_video_file(missing_file)
        assert error is not None
        assert "not found" in error.lower()

    def test_directory_not_file_returns_error(self, temp_dir):
        """Directory path returns error."""
        error = validate_video_file(temp_dir)
        assert error is not None
        assert "not a file" in error.lower()

    def test_invalid_extension_returns_error(self, temp_dir):
        """File with non-video extension returns error."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("not a video")
        error = validate_video_file(txt_file)
        assert error is not None
        assert "unsupported" in error.lower()

    @pytest.mark.parametrize(
        "extension",
        [".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"],
    )
    def test_common_video_extensions_accepted(self, temp_dir, extension):
        """Common video extensions are accepted."""
        video_file = temp_dir / f"test{extension}"
        video_file.write_bytes(b"fake video")
        error = validate_video_file(video_file)
        assert error is None


class TestCheckFileSize:
    """Tests for check_file_size()."""

    def test_small_file_returns_none(self, mock_video_file):
        """Small file (<50GB) returns None."""
        warning = check_file_size(mock_video_file)
        assert warning is None

    def test_large_file_returns_warning(self, temp_dir):
        """File >50GB returns warning message."""
        # Create a file
        large_file = temp_dir / "large.mp4"
        large_file.write_bytes(b"x")

        # Mock stat to return large size
        class MockStat:
            st_size = 60 * 1024 * 1024 * 1024  # 60GB

        with mock.patch.object(Path, "stat", return_value=MockStat()):
            warning = check_file_size(large_file)
            assert warning is not None
            assert "large file" in warning.lower()
            assert "60" in warning  # Size in GB


class TestCheckDiskSpace:
    """Tests for check_disk_space()."""

    def test_sufficient_space_returns_none(self, temp_dir):
        """Sufficient disk space returns None."""
        # Most test environments have >5GB free
        required = 1024 * 1024  # 1MB (tiny)
        error = check_disk_space(temp_dir, required)
        assert error is None

    def test_insufficient_space_returns_error(self, temp_dir, monkeypatch):
        """Insufficient disk space returns error."""
        import shutil

        # Mock disk_usage to return low free space
        class MockUsage:
            free = 100 * 1024 * 1024  # 100MB

        def mock_disk_usage(path):
            return MockUsage()

        monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

        # Require 1GB (more than 100MB available)
        required = 1024 * 1024 * 1024
        error = check_disk_space(temp_dir, required)
        assert error is not None
        assert "insufficient" in error.lower()


class TestGetProjectsDir:
    """Tests for get_projects_dir()."""

    def test_creates_directory_if_missing(self, temp_dir, monkeypatch):
        """Creates ~/.videotool/projects if it doesn't exist."""
        # Mock Path.home() to return temp_dir
        def mock_home():
            return temp_dir

        monkeypatch.setattr(Path, "home", mock_home)

        projects_dir = get_projects_dir()
        assert projects_dir.exists()
        assert projects_dir.is_dir()
        assert projects_dir.name == "projects"
        assert projects_dir.parent.name == ".videotool"

    def test_returns_existing_directory(self, temp_dir, monkeypatch):
        """Returns existing directory if already created."""

        def mock_home():
            return temp_dir

        monkeypatch.setattr(Path, "home", mock_home)

        # Call twice - second call should return same path
        dir1 = get_projects_dir()
        dir2 = get_projects_dir()
        assert dir1 == dir2
        assert dir1.exists()
