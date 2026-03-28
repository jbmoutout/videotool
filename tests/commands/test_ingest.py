"""Tests for vodtool.commands.ingest module."""

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from vodtool.commands.ingest import (
    check_ffmpeg_available,
    extract_audio,
    get_ffprobe_path,
    get_last_error,
    get_video_duration,
    ingest_video,
)


class TestCheckFfmpegAvailable:
    """Tests for check_ffmpeg_available()."""

    def test_found(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            assert check_ffmpeg_available("ffmpeg") is True

    def test_not_found(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_ffmpeg_available("ffmpeg") is False

    def test_nonzero_exit(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            assert check_ffmpeg_available("ffmpeg") is False


class TestGetFfprobePath:
    """Tests for get_ffprobe_path()."""

    def test_simple(self):
        assert get_ffprobe_path("ffmpeg") == "ffprobe"

    def test_full_path_with_ffmpeg_name(self):
        # When the binary name is exactly "ffmpeg", returns just "ffprobe"
        assert get_ffprobe_path("/usr/local/bin/ffmpeg") == "ffprobe"

    def test_custom_name(self):
        # When the binary has a non-standard name, replaces "ffmpeg" portion
        assert get_ffprobe_path("/opt/bin/ffmpeg-7") == "/opt/bin/ffprobe-7"


class TestGetVideoDuration:
    """Tests for get_video_duration()."""

    def test_success(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="3600.5\n"
            )
            result = get_video_duration(video)
            assert result == 3600.5

    def test_timeout(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 30)):
            result = get_video_duration(video)
            assert result is None

    def test_file_not_found(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_video_duration(video)
            assert result is None


class TestExtractAudio:
    """Tests for extract_audio()."""

    def test_success(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "audio.wav"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stderr="")
            result = extract_audio(video, output)
            assert result is True

    def test_failure(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "audio.wav"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr="error")
            result = extract_audio(video, output)
            assert result is False


class TestIngestVideo:
    """Integration-level tests for ingest_video()."""

    def test_no_ffmpeg(self, monkeypatch):
        monkeypatch.setattr(
            "vodtool.commands.ingest.check_ffmpeg_available", lambda _: False
        )
        result = ingest_video("/tmp/nonexistent.mp4")
        assert result is None
        assert get_last_error() is not None
        assert "ffmpeg" in get_last_error().lower()

    def test_invalid_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "vodtool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        bad_file = tmp_path / "not_a_video.txt"
        bad_file.write_text("hello")
        result = ingest_video(str(bad_file))
        assert result is None
        assert get_last_error() is not None

    def test_nonexistent_file(self, monkeypatch):
        monkeypatch.setattr(
            "vodtool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        result = ingest_video("/tmp/does_not_exist_12345.mp4")
        assert result is None
        assert get_last_error() is not None
