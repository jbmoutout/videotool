"""Tests for videotool.commands.transcribe module."""

import json
from pathlib import Path
from unittest import mock

import pytest

from videotool.commands.transcribe import (
    get_last_error,
    transcribe_audio,
)


class TestTranscribeAudio:
    """Tests for transcribe_audio() error paths."""

    def test_invalid_project(self, tmp_path):
        """Nonexistent project path returns None with _last_error set."""
        result = transcribe_audio(tmp_path / "nonexistent")
        assert result is None
        assert get_last_error() is not None

    def test_no_audio_file(self, tmp_path):
        """Project without audio.wav returns None."""
        # Create minimal project structure (meta.json but no audio.wav)
        (tmp_path / "meta.json").write_text(json.dumps({
            "project_id": "test",
            "audio_path": "audio.wav",
            "duration_seconds": 60,
        }))
        result = transcribe_audio(tmp_path)
        assert result is None
        assert get_last_error() is not None

    def test_already_exists_no_force(self, tmp_path):
        """Existing transcript without --force returns existing path."""
        (tmp_path / "meta.json").write_text(json.dumps({
            "project_id": "test",
            "audio_path": "audio.wav",
            "duration_seconds": 60,
        }))
        (tmp_path / "audio.wav").write_bytes(b"fake audio")
        transcript_path = tmp_path / "transcript_raw.json"
        transcript_path.write_text(json.dumps({
            "segments": [{"start": 0, "end": 5, "text": "hello"}],
        }))
        result = transcribe_audio(tmp_path, force=False)
        assert result == transcript_path

    def test_write_failure_sets_last_error(self, tmp_path):
        """When safe_write_json fails, _last_error is set."""
        (tmp_path / "meta.json").write_text(json.dumps({
            "project_id": "test",
            "audio_path": "audio.wav",
            "duration_seconds": 60,
        }))
        (tmp_path / "audio.wav").write_bytes(b"fake audio")

        mock_provider = mock.Mock()
        mock_provider.transcribe.return_value = {
            "segments": [{"start": 0, "end": 5, "text": "hello"}],
            "language": "en",
        }

        with mock.patch("videotool.commands.transcribe.safe_write_json", return_value=False):
            with mock.patch(
                "videotool.transcription.GroqTranscriptionProvider",
                return_value=mock_provider,
            ):
                result = transcribe_audio(tmp_path, force=True, provider="groq")

        assert result is None
        assert get_last_error() is not None
        assert "write" in get_last_error().lower()
