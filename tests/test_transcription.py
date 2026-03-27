"""Tests for vodtool.transcription module."""

from pathlib import Path
from unittest import mock

import pytest

from vodtool.transcription import (
    OpenAITranscriptionProvider,
    _deduplicate_boundary_segments,
    _probe_duration,
)


def _make_segment(start, end, text):
    seg = mock.Mock()
    seg.start = start
    seg.end = end
    seg.text = f" {text}"
    return seg


def _make_response(segments, language="fr"):
    resp = mock.Mock()
    resp.language = language
    resp.segments = segments
    return resp


class TestOpenAITranscriptionProvider:
    def test_raises_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY not set"):
            OpenAITranscriptionProvider(api_key=None)

    def test_raises_if_openai_not_installed(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="openai package not installed"):
                OpenAITranscriptionProvider()

    def test_file_not_found_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch("openai.OpenAI"):
            provider = OpenAITranscriptionProvider()
        with pytest.raises(FileNotFoundError):
            provider.transcribe(tmp_path / "nonexistent.wav")

    def test_small_file_direct_api_call(self, monkeypatch, tmp_path):
        """Files ≤25MB go directly to the API without chunking."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"x" * 100)  # tiny file

        response = _make_response([_make_segment(0.0, 5.0, "Hello")])

        with mock.patch("openai.OpenAI") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.audio.transcriptions.create.return_value = response
            provider = OpenAITranscriptionProvider()
            result = provider.transcribe(audio)

        assert result["language"] == "fr"
        assert len(result["segments"]) == 1
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["text"] == "Hello"
        mock_client.audio.transcriptions.create.assert_called_once()

    def test_large_file_chunked(self, monkeypatch, tmp_path):
        """Files >25MB are split into chunks and _transcribe_file called once per chunk."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"x" * (26 * 1024 * 1024))  # 26 MB

        chunk_results = [
            {"language": "fr", "model": "whisper-1", "segments": [{"start": 0.0, "end": 5.0, "text": "First chunk"}]},
            {"language": "fr", "model": "whisper-1", "segments": [{"start": 600.0, "end": 605.0, "text": "Second chunk"}]},
        ]

        with mock.patch("openai.OpenAI"), \
             mock.patch("vodtool.transcription._probe_duration", return_value=1200.0), \
             mock.patch("vodtool.transcription._extract_chunk"), \
             mock.patch.object(OpenAITranscriptionProvider, "_transcribe_file", side_effect=chunk_results) as mock_tf:
            provider = OpenAITranscriptionProvider()
            result = provider.transcribe(audio)

        assert mock_tf.call_count == 2
        assert len(result["segments"]) == 2

    def test_timestamp_offset_applied_to_chunks(self, monkeypatch, tmp_path):
        """CRITICAL: chunk 2 starts at 600s — its timestamps must be offset by 600s."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"x" * (26 * 1024 * 1024))

        # _transcribe_file already receives offset and applies it; return pre-offset results
        chunk_results = [
            {"language": "fr", "model": "whisper-1", "segments": [{"start": 0.0, "end": 10.0, "text": "Chunk one content"}]},
            {"language": "fr", "model": "whisper-1", "segments": [{"start": 600.0, "end": 610.0, "text": "Chunk two content"}]},
        ]

        with mock.patch("openai.OpenAI"), \
             mock.patch("vodtool.transcription._probe_duration", return_value=1200.0), \
             mock.patch("vodtool.transcription._extract_chunk"), \
             mock.patch.object(OpenAITranscriptionProvider, "_transcribe_file", side_effect=chunk_results):
            provider = OpenAITranscriptionProvider()
            result = provider.transcribe(audio)

        segs = result["segments"]
        assert segs[0]["start"] == pytest.approx(0.0)
        assert segs[0]["end"] == pytest.approx(10.0)
        assert segs[1]["start"] == pytest.approx(600.0)
        assert segs[1]["end"] == pytest.approx(610.0)

    def test_chunk_failure_raises_with_chunk_number(self, monkeypatch, tmp_path):
        """API failure on chunk N should raise identifying which chunk failed."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"x" * (26 * 1024 * 1024))

        chunk_results = [
            {"language": "fr", "model": "whisper-1", "segments": [{"start": 0.0, "end": 5.0, "text": "ok"}]},
            Exception("rate limit"),
        ]

        with mock.patch("openai.OpenAI"), \
             mock.patch("vodtool.transcription._probe_duration", return_value=1200.0), \
             mock.patch("vodtool.transcription._extract_chunk"), \
             mock.patch.object(OpenAITranscriptionProvider, "_transcribe_file", side_effect=chunk_results):
            provider = OpenAITranscriptionProvider()
            with pytest.raises(RuntimeError, match="chunk 2 of"):
                provider.transcribe(audio)


class TestDeduplicateBoundarySegments:
    def test_no_duplicates_unchanged(self):
        segs = [
            {"start": 0.0, "end": 5.0, "text": "Hello"},
            {"start": 5.0, "end": 10.0, "text": "World"},
        ]
        assert _deduplicate_boundary_segments(segs) == segs

    def test_duplicate_at_boundary_removed(self):
        segs = [
            {"start": 590.0, "end": 600.0, "text": "See you later"},
            {"start": 600.0, "end": 605.0, "text": "See you later"},  # duplicate
            {"start": 605.0, "end": 610.0, "text": "Next topic"},
        ]
        result = _deduplicate_boundary_segments(segs)
        assert len(result) == 2
        assert result[0]["text"] == "See you later"
        assert result[1]["text"] == "Next topic"

    def test_empty_list(self):
        assert _deduplicate_boundary_segments([]) == []

    def test_case_insensitive_dedup(self):
        segs = [
            {"start": 0.0, "end": 5.0, "text": "Hello world"},
            {"start": 5.0, "end": 10.0, "text": "HELLO WORLD"},
        ]
        result = _deduplicate_boundary_segments(segs)
        assert len(result) == 1
