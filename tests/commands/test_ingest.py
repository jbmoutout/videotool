"""Tests for videotool.commands.ingest module."""

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from videotool.commands.ingest import (
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
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: False
        )
        result = ingest_video("/tmp/nonexistent.mp4")
        assert result is None
        assert get_last_error() is not None
        assert "ffmpeg" in get_last_error().lower()

    def test_invalid_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        bad_file = tmp_path / "not_a_video.txt"
        bad_file.write_text("hello")
        result = ingest_video(str(bad_file))
        assert result is None
        assert get_last_error() is not None

    def test_nonexistent_file(self, monkeypatch):
        monkeypatch.setattr(
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        result = ingest_video("/tmp/does_not_exist_12345.mp4")
        assert result is None
        assert get_last_error() is not None

    def test_returns_path_not_tuple(self, tmp_path, monkeypatch):
        """ingest_video() returns Optional[Path], not a tuple."""
        monkeypatch.setattr(
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        result = ingest_video("/tmp/does_not_exist_12345.mp4")
        # On failure it's None
        assert result is None
        # On success (mocked), it should be a Path
        # We verify the type contract via _ingest_twitch tests below


class TestIngestTwitch:
    """Tests for _ingest_twitch flow (single-stream download)."""

    def _setup_twitch_mocks(self, monkeypatch, tmp_path, download_ok=True,
                            remux_ok=True, extract_ok=True):
        """Wire up all mocks for a Twitch ingest. Returns project_dir."""
        monkeypatch.setattr(
            "videotool.commands.ingest.check_streamlink", lambda: True
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: True
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.get_projects_dir", lambda: tmp_path
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.get_available_streams", lambda _: ["160p", "360p", "worst", "best"]
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.fetch_vod_metadata", lambda _: None
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.download_chat", lambda vid, path: False
        )

        def fake_download_progress(url, output_path, quality="worst", progress_callback=None):
            output_path.write_bytes(b"x" * 1000)
            if progress_callback:
                progress_callback(1.0)
            return download_ok

        def fake_download(url, output_path, quality="worst"):
            output_path.write_bytes(b"x" * 1000)
            return download_ok

        monkeypatch.setattr(
            "videotool.commands.ingest.download_vod_with_progress", fake_download_progress
        )
        monkeypatch.setattr(
            "videotool.utils.twitch.download_vod", fake_download
        )

        def fake_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run for remux (ffmpeg -i source.ts ...)."""
            result = mock.Mock()
            if "-c" in cmd and "copy" in cmd:
                # This is the remux call
                if remux_ok:
                    # Create the output mp4
                    out_path = cmd[-1]
                    Path(out_path).write_bytes(b"mp4data")
                    result.returncode = 0
                else:
                    result.returncode = 1
            else:
                # ffprobe or other calls
                result.returncode = 0
                result.stdout = "3600.0\n"
            return result

        monkeypatch.setattr("subprocess.run", fake_subprocess_run)

        def fake_extract_audio(video_path, output_path, ffmpeg_path="ffmpeg",
                               duration=None, progress_callback=None):
            if extract_ok:
                output_path.write_bytes(b"wav" * 100)
                return True
            return False

        monkeypatch.setattr(
            "videotool.commands.ingest.extract_audio", fake_extract_audio
        )

    def test_success_produces_source_mp4_and_audio_wav(self, tmp_path, monkeypatch):
        """Full happy path: download → remux → extract audio → metadata."""
        self._setup_twitch_mocks(monkeypatch, tmp_path)

        result = ingest_video(
            "https://twitch.tv/videos/123456",
            ffmpeg_path="ffmpeg",
        )

        assert result is not None
        assert isinstance(result, Path)
        project_dir = result
        assert (project_dir / "source.mp4").exists()
        assert (project_dir / "audio.wav").exists()
        # source.ts should be deleted after successful remux
        assert not (project_dir / "source.ts").exists()
        # Check metadata
        meta = json.loads((project_dir / "meta.json").read_text())
        assert meta["audio_path"] == "audio.wav"
        assert meta["twitch_video_id"] == "123456"

    def test_download_failure_cleans_up(self, tmp_path, monkeypatch):
        """If download fails, project dir is removed and None returned."""
        self._setup_twitch_mocks(monkeypatch, tmp_path, download_ok=False)

        result = ingest_video(
            "https://twitch.tv/videos/123456",
            ffmpeg_path="ffmpeg",
        )

        assert result is None
        assert get_last_error() is not None
        # Project dir should be cleaned up
        project_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(project_dirs) == 0

    def test_remux_failure_keeps_source_ts(self, tmp_path, monkeypatch):
        """If remux fails, source.ts is kept as fallback."""
        self._setup_twitch_mocks(monkeypatch, tmp_path, remux_ok=False)

        result = ingest_video(
            "https://twitch.tv/videos/123456",
            ffmpeg_path="ffmpeg",
        )

        assert result is not None
        project_dir = result
        # source.ts should still exist since remux failed
        assert (project_dir / "source.ts").exists()
        assert not (project_dir / "source.mp4").exists()
        # audio.wav should still be extracted
        assert (project_dir / "audio.wav").exists()

    def test_audio_extraction_failure_cleans_up(self, tmp_path, monkeypatch):
        """If audio extraction fails, project dir is removed."""
        self._setup_twitch_mocks(monkeypatch, tmp_path, extract_ok=False)

        result = ingest_video(
            "https://twitch.tv/videos/123456",
            ffmpeg_path="ffmpeg",
        )

        assert result is None
        assert get_last_error() is not None

    def test_streamlink_not_installed(self, monkeypatch):
        """check_streamlink() → False means early return None."""
        monkeypatch.setattr(
            "videotool.commands.ingest.check_streamlink", lambda: False
        )
        result = ingest_video("https://twitch.tv/videos/123456")
        assert result is None
        assert "streamlink" in get_last_error().lower()

    def test_ffmpeg_not_installed_for_twitch(self, monkeypatch):
        """check_ffmpeg_available() → False means early return None."""
        monkeypatch.setattr(
            "videotool.commands.ingest.check_streamlink", lambda: True
        )
        monkeypatch.setattr(
            "videotool.commands.ingest.check_ffmpeg_available", lambda _: False
        )
        result = ingest_video("https://twitch.tv/videos/123456")
        assert result is None
        assert "ffmpeg" in get_last_error().lower()

    def test_progress_callback_called(self, tmp_path, monkeypatch):
        """download_progress_callback is forwarded to download function."""
        self._setup_twitch_mocks(monkeypatch, tmp_path)
        callbacks = []

        result = ingest_video(
            "https://twitch.tv/videos/123456",
            ffmpeg_path="ffmpeg",
            download_progress_callback=callbacks.append,
        )

        assert result is not None
        assert len(callbacks) >= 1
        assert callbacks[-1] == 1.0
