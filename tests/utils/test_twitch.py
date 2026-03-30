"""Tests for videotool.utils.twitch module."""

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from videotool.utils.twitch import (
    check_streamlink,
    download_vod,
    download_vod_with_progress,
    get_available_streams,
    is_twitch_url,
    parse_twitch_video_id,
    resolve_quality,
    summarize_chat_for_prompt,
)


class TestParseTwitchVideoId:
    """Tests for parse_twitch_video_id()."""

    def test_valid_url(self):
        assert parse_twitch_video_id("https://twitch.tv/videos/123456") == "123456"

    def test_valid_url_with_path(self):
        assert parse_twitch_video_id("https://www.twitch.tv/videos/9876543210") == "9876543210"

    def test_invalid_url(self):
        assert parse_twitch_video_id("https://youtube.com/watch?v=abc") is None

    def test_no_video_id(self):
        assert parse_twitch_video_id("https://twitch.tv/channel") is None

    def test_empty(self):
        assert parse_twitch_video_id("") is None


class TestIsTwitchUrl:
    """Tests for is_twitch_url()."""

    def test_valid(self):
        assert is_twitch_url("https://twitch.tv/videos/123456") is True

    def test_with_www(self):
        assert is_twitch_url("https://www.twitch.tv/videos/789") is True

    def test_not_twitch(self):
        assert is_twitch_url("https://youtube.com/watch?v=abc") is False

    def test_local_file(self):
        assert is_twitch_url("/path/to/video.mp4") is False

    def test_empty(self):
        assert is_twitch_url("") is False


class TestCheckStreamlink:
    """Tests for check_streamlink()."""

    def test_available(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            assert check_streamlink() is True

    def test_not_found(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_streamlink() is False

    def test_broken(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            assert check_streamlink() is False


class TestDownloadVod:
    """Tests for download_vod()."""

    def test_success(self, tmp_path):
        output = tmp_path / "vod.mp4"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            # Create the output file to simulate download
            output.write_bytes(b"video data")
            result = download_vod("https://twitch.tv/videos/123", output)
            assert result is True

    def test_failure(self, tmp_path):
        output = tmp_path / "vod.mp4"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            result = download_vod("https://twitch.tv/videos/123", output)
            assert result is False

    def test_timeout(self, tmp_path):
        output = tmp_path / "vod.mp4"
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("streamlink", 7200)):
            result = download_vod("https://twitch.tv/videos/123", output)
            assert result is False


class TestGetAvailableStreams:
    """Tests for get_available_streams()."""

    def test_success(self):
        fake_json = json.dumps({
            "streams": {
                "audio": {"type": "hls"},
                "480p": {"type": "hls"},
                "720p60": {"type": "hls"},
                "best": {"type": "hls"},
                "worst": {"type": "hls"},
            }
        })
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=fake_json)
            result = get_available_streams("https://twitch.tv/videos/123")
            assert result == ["audio", "480p", "720p60", "best", "worst"]
            mock_run.assert_called_once()
            # Verify stderr is suppressed (DEVNULL)
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("stderr") == subprocess.DEVNULL

    def test_non_zero_exit(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            result = get_available_streams("https://twitch.tv/videos/123")
            assert result is None

    def test_timeout(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = get_available_streams("https://twitch.tv/videos/123")
            assert result is None

    def test_invalid_json(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="not json")
            result = get_available_streams("https://twitch.tv/videos/123")
            assert result is None

    def test_empty_streams(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout='{"streams":{}}')
            result = get_available_streams("https://twitch.tv/videos/123")
            assert result == []


class TestResolveQuality:
    """Tests for resolve_quality()."""

    TYPICAL_STREAMS = ["audio", "160p", "360p", "480p", "720p60", "1080p60", "worst", "best"]

    def test_direct_match_first_choice(self):
        assert resolve_quality("480p", self.TYPICAL_STREAMS) == "480p"

    def test_direct_match_second_choice(self):
        assert resolve_quality("480p60,480p", self.TYPICAL_STREAMS) == "480p"

    def test_audio_match(self):
        assert resolve_quality("audio,audio_only", self.TYPICAL_STREAMS) == "audio"

    def test_audio_only_fallback_to_audio(self):
        """Old 'audio_only' name falls back to 'audio' on new streamlink."""
        assert resolve_quality("audio_only,audio", self.TYPICAL_STREAMS) == "audio"

    def test_fallback_nearest_lower(self):
        """720p not available, should fall back to 480p (nearest lower)."""
        streams = ["audio", "160p", "360p", "480p", "1080p60", "best"]
        assert resolve_quality("720p", streams) == "480p"

    def test_fallback_nearest_higher(self):
        """160p requested but not available, 360p is nearest."""
        streams = ["audio", "360p", "480p", "best"]
        assert resolve_quality("160p", streams) == "360p"

    def test_fallback_to_best(self):
        """No ladder match at all — fall back to 'best'."""
        streams = ["audio", "best", "worst"]
        assert resolve_quality("720p", streams) == "best"

    def test_no_match_returns_first_candidate(self):
        """Nothing matches at all — return the first requested quality."""
        assert resolve_quality("audio_only", ["best"]) == "best"

    def test_comma_separated_with_spaces(self):
        assert resolve_quality("480p , 480p60", self.TYPICAL_STREAMS) == "480p"

    def test_worst_passthrough(self):
        """'worst' is not on the ladder but is in available."""
        assert resolve_quality("worst", self.TYPICAL_STREAMS) == "worst"


class TestDownloadVodWithProgress:
    """Tests for download_vod_with_progress()."""

    def test_success_calls_callback(self, tmp_path):
        output = tmp_path / "audio.ts"
        callbacks = []

        def _track(pct):
            callbacks.append(pct)

        # Simulate: process writes file, then exits
        def fake_popen(*args, **kwargs):
            proc = mock.MagicMock()
            # poll() returns None twice (running), then 0 (done)
            proc.poll.side_effect = [None, None, 0]
            proc.returncode = 0
            # Create the file with some data on first poll
            output.write_bytes(b"x" * 2_000_000)
            return proc

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with mock.patch("time.sleep"):  # skip real waits
                result = download_vod_with_progress(
                    "https://twitch.tv/videos/123", output,
                    quality="audio", progress_callback=_track,
                )
        assert result is True
        # Must have called callback with 1.0 at the end
        assert callbacks[-1] == 1.0
        # Should have intermediate values
        assert len(callbacks) >= 2

    def test_failure_returns_false(self, tmp_path):
        output = tmp_path / "audio.ts"

        def fake_popen(*args, **kwargs):
            proc = mock.MagicMock()
            proc.poll.side_effect = [None, 1]
            proc.returncode = 1
            return proc

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with mock.patch("time.sleep"):
                result = download_vod_with_progress(
                    "https://twitch.tv/videos/123", output,
                    quality="audio",
                )
        assert result is False

    def test_progress_never_exceeds_one(self, tmp_path):
        output = tmp_path / "audio.ts"
        callbacks = []

        def fake_popen(*args, **kwargs):
            proc = mock.MagicMock()
            # Simulate long download with growing file
            poll_results = [None] * 10 + [0]
            proc.poll.side_effect = poll_results
            proc.returncode = 0
            # Write progressively larger file
            output.write_bytes(b"x" * 100_000_000)
            return proc

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with mock.patch("time.sleep"):
                download_vod_with_progress(
                    "https://twitch.tv/videos/123", output,
                    quality="audio", progress_callback=callbacks.append,
                )
        # No callback value should exceed 1.0
        assert all(0 <= c <= 1.0 for c in callbacks)
        assert callbacks[-1] == 1.0

    def test_empty_file_still_completes(self, tmp_path):
        """If streamlink exits successfully but file is empty, return False."""
        output = tmp_path / "audio.ts"

        def fake_popen(*args, **kwargs):
            proc = mock.MagicMock()
            proc.poll.side_effect = [None, 0]
            proc.returncode = 0
            return proc

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with mock.patch("time.sleep"):
                result = download_vod_with_progress(
                    "https://twitch.tv/videos/123", output,
                    quality="audio",
                )
        # File doesn't exist → False
        assert result is False


class TestSummarizeChatForPrompt:
    """Tests for summarize_chat_for_prompt()."""

    def test_nonexistent_file(self, tmp_path):
        result = summarize_chat_for_prompt(tmp_path / "chat.json")
        assert result is None

    def test_empty_messages(self, tmp_path):
        chat_path = tmp_path / "chat.json"
        chat_path.write_text("[]")
        result = summarize_chat_for_prompt(chat_path)
        assert result is None

    def test_sampling(self, tmp_path):
        """500 messages with max_messages=100 should sample evenly."""
        messages = [
            {"offset": i * 10, "user": f"user{i}", "text": f"msg{i}"}
            for i in range(500)
        ]
        chat_path = tmp_path / "chat.json"
        chat_path.write_text(json.dumps(messages))
        result = summarize_chat_for_prompt(chat_path, max_messages=100)
        assert result is not None
        lines = result.strip().split("\n")
        assert len(lines) == 100
        # First message should be the start, last should be near the end
        assert "user0" in lines[0]
        # Even sampling with step=5.0 picks index 495 last, not 499
        assert "user49" in lines[-1]

    def test_small_chat_no_sampling(self, tmp_path):
        """Fewer messages than max_messages returns all."""
        messages = [
            {"offset": i, "user": f"u{i}", "text": f"hi{i}"}
            for i in range(5)
        ]
        chat_path = tmp_path / "chat.json"
        chat_path.write_text(json.dumps(messages))
        result = summarize_chat_for_prompt(chat_path, max_messages=100)
        lines = result.strip().split("\n")
        assert len(lines) == 5
