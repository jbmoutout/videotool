"""Tests for vodtool.utils.twitch module."""

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from vodtool.utils.twitch import (
    check_streamlink,
    download_vod,
    is_twitch_url,
    parse_twitch_video_id,
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
