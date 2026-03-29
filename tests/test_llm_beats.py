"""Tests for vodtool.commands.llm_beats module."""

import json
from unittest import mock

import pytest

from vodtool.commands.llm_beats import (
    _parse_beats_response,
    validate_beats,
)


# ── Sample data ──────────────────────────────────────────────────────────────

VALID_BEATS = {
    "beats": [
        {
            "topic_id": "topic_0001",
            "topic_label": "Harry Potter casting",
            "beats": [
                {"type": "hook", "start_s": 100, "end_s": 130, "confidence": 0.91, "label": "Hot take"},
                {"type": "peak", "start_s": 200, "end_s": 400, "confidence": 0.85, "label": "Main argument"},
                {"type": "resolution", "start_s": 400, "end_s": 450, "confidence": 0.6, "label": "Wind down"},
            ],
        },
    ],
}

STREAM_DURATION = 3600.0  # 1 hour


# ── Test validate_beats ──────────────────────────────────────────────────────


class TestValidateBeats:
    """Tests for validate_beats()."""

    def test_valid_data_passes(self):
        """Valid beats data passes validation unchanged."""
        result = validate_beats(VALID_BEATS, STREAM_DURATION)
        assert len(result["beats"]) == 1
        assert len(result["beats"][0]["beats"]) == 3
        assert result["beats"][0]["beats"][0]["type"] == "hook"

    def test_invalid_type_dropped(self):
        """Beats with invalid type are dropped."""
        data = {
            "beats": [
                {
                    "topic_id": "t1",
                    "topic_label": "Test",
                    "beats": [
                        {"type": "hook", "start_s": 10, "end_s": 20, "confidence": 0.9, "label": "ok"},
                        {"type": "climax", "start_s": 30, "end_s": 40, "confidence": 0.8, "label": "bad type"},
                    ],
                },
            ],
        }
        result = validate_beats(data, STREAM_DURATION)
        assert len(result["beats"][0]["beats"]) == 1
        assert result["beats"][0]["beats"][0]["type"] == "hook"

    def test_timestamps_clamped_to_stream_duration(self):
        """Timestamps beyond stream duration are clamped."""
        data = {
            "beats": [
                {
                    "topic_id": "t1",
                    "topic_label": "Test",
                    "beats": [
                        {"type": "peak", "start_s": 3500, "end_s": 4000, "confidence": 0.8, "label": "over"},
                    ],
                },
            ],
        }
        result = validate_beats(data, STREAM_DURATION)
        beat = result["beats"][0]["beats"][0]
        assert beat["end_s"] == STREAM_DURATION
        assert beat["start_s"] == 3500

    def test_start_gte_end_after_clamping_dropped(self):
        """Beats where start_s >= end_s after clamping are dropped."""
        data = {
            "beats": [
                {
                    "topic_id": "t1",
                    "topic_label": "Test",
                    "beats": [
                        # Both beyond duration → both clamp to 3600 → start >= end → dropped
                        {"type": "peak", "start_s": 3700, "end_s": 3800, "confidence": 0.8, "label": "bad"},
                        # Valid beat to keep the topic alive
                        {"type": "hook", "start_s": 10, "end_s": 20, "confidence": 0.9, "label": "ok"},
                    ],
                },
            ],
        }
        result = validate_beats(data, STREAM_DURATION)
        assert len(result["beats"][0]["beats"]) == 1
        assert result["beats"][0]["beats"][0]["type"] == "hook"

    def test_missing_beats_key_raises(self):
        """beats_data without 'beats' key raises ValueError."""
        with pytest.raises(ValueError, match="must have a 'beats' key"):
            validate_beats({"topics": []}, STREAM_DURATION)


# ── Test _parse_beats_response ───────────────────────────────────────────────


class TestParseBeatsResponse:
    """Tests for _parse_beats_response()."""

    def test_valid_json_parsed(self):
        """Valid JSON response is parsed correctly."""
        response = json.dumps(VALID_BEATS)
        result = _parse_beats_response(response)
        assert "beats" in result
        assert len(result["beats"]) == 1

    def test_malformed_json_raises(self):
        """Malformed JSON raises ValueError."""
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_beats_response("{not valid json}")

    def test_markdown_code_block_stripped(self):
        """Markdown code block fencing is stripped before parsing."""
        response = "```json\n" + json.dumps(VALID_BEATS) + "\n```"
        result = _parse_beats_response(response)
        assert "beats" in result
        assert len(result["beats"]) == 1


# ── Test detect_beats (API key missing) ──────────────────────────────────────


class TestDetectBeats:
    """Integration-level tests for detect_beats()."""

    def test_api_key_missing_returns_none(self, tmp_path, monkeypatch):
        """Missing ANTHROPIC_API_KEY returns None with clear error."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        # Create minimal project structure
        (tmp_path / "meta.json").write_text(json.dumps({"duration_seconds": 60}))
        (tmp_path / "transcript_raw.json").write_text(json.dumps({
            "language": "fr",
            "model": "whisper-1",
            "segments": [{"start": 0, "end": 5, "text": "bonjour"}],
        }))

        from vodtool.commands.llm_beats import detect_beats

        result = detect_beats(tmp_path)
        assert result is None

    def test_no_project_dir(self, tmp_path):
        """Nonexistent project directory returns None."""
        from vodtool.commands.llm_beats import detect_beats, get_last_error

        result = detect_beats(tmp_path / "nonexistent")
        assert result is None
        assert get_last_error() is not None

    def test_no_transcript(self, tmp_path):
        """Project without transcript_raw.json returns None."""
        from vodtool.commands.llm_beats import detect_beats, get_last_error

        (tmp_path / "meta.json").write_text(json.dumps({"duration_seconds": 60}))
        result = detect_beats(tmp_path)
        assert result is None
        assert get_last_error() is not None
        assert "transcript" in get_last_error().lower()

    def test_empty_segments(self, tmp_path):
        """Transcript with empty segments list returns None."""
        from vodtool.commands.llm_beats import detect_beats, get_last_error

        (tmp_path / "meta.json").write_text(json.dumps({"duration_seconds": 60}))
        (tmp_path / "transcript_raw.json").write_text(json.dumps({
            "segments": [],
        }))
        result = detect_beats(tmp_path)
        assert result is None
        assert get_last_error() is not None

    def test_write_failure_sets_last_error(self, tmp_path, monkeypatch):
        """When safe_write_json fails, _last_error is set."""
        from vodtool.commands.llm_beats import detect_beats, get_last_error

        (tmp_path / "meta.json").write_text(json.dumps({"duration_seconds": 3600}))
        (tmp_path / "transcript_raw.json").write_text(json.dumps({
            "segments": [{"start": 0, "end": 5, "text": "hello"}],
        }))

        mock_response = mock.Mock()
        mock_response.content = [mock.Mock(text=json.dumps(VALID_BEATS))]

        mock_client = mock.Mock()
        mock_client.messages.create.return_value = mock_response

        monkeypatch.setattr(
            "vodtool.llm.get_anthropic_client", lambda: mock_client
        )
        monkeypatch.setattr(
            "vodtool.commands.llm_beats.safe_write_json", lambda *a, **kw: False
        )

        result = detect_beats(tmp_path)
        assert result is None
        assert get_last_error() is not None
        assert "write" in get_last_error().lower()
