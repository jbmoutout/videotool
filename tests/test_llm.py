"""Tests for videotool.llm module."""

import json
from unittest import mock

import pytest

from videotool.llm import (
    _build_topic_extraction_prompt,
    _estimate_token_count,
    _parse_topic_response,
    get_anthropic_client,
    get_ollama_client,
    segment_topics_with_llm,
    segment_topics_with_local_llm,
)


class TestGetAnthropicClient:
    """Tests for get_anthropic_client()."""

    def test_raises_import_error_if_anthropic_not_installed(self):
        """Raises ImportError if anthropic package not installed."""
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic package not installed"):
                get_anthropic_client()

    def test_raises_value_error_if_api_key_missing(self, monkeypatch):
        """Raises ValueError if ANTHROPIC_API_KEY not set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("VITE_API_PROXY_URL", raising=False)
        monkeypatch.delenv("PROXY_AUTH_TOKEN", raising=False)

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            get_anthropic_client()

    def test_returns_client_with_valid_api_key(self, monkeypatch, stub_module):
        """Returns Anthropic client when API key is set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-123")

        mock_anthropic = mock.Mock()
        with stub_module("anthropic", Anthropic=mock_anthropic):
            client = get_anthropic_client()
            mock_anthropic.assert_called_once_with(api_key="test-api-key-123")
            assert client == mock_anthropic.return_value


class TestGetOllamaClient:
    """Tests for get_ollama_client()."""

    def test_raises_import_error_if_openai_not_installed(self):
        """Raises ImportError if openai package not installed."""
        with mock.patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="openai package not installed"):
                get_ollama_client()

    def test_raises_connection_error_if_ollama_not_running(self, stub_module):
        """Raises ConnectionError if Ollama server not accessible."""
        mock_openai = mock.Mock()
        with stub_module("openai", OpenAI=mock_openai):
            mock_client = mock_openai.return_value
            mock_client.models.retrieve.side_effect = Exception("Connection refused")

            with pytest.raises(ConnectionError, match="Ollama not running"):
                get_ollama_client("qwen2.5:3b")

    def test_returns_client_when_ollama_accessible(self, stub_module):
        """Returns OpenAI client configured for Ollama when server is running."""
        mock_openai = mock.Mock()
        with stub_module("openai", OpenAI=mock_openai):
            mock_client = mock_openai.return_value
            mock_client.models.retrieve.return_value = {"id": "qwen2.5:3b"}

            client = get_ollama_client("qwen2.5:3b")

            mock_openai.assert_called_once_with(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
            assert client == mock_client


class TestBuildTopicExtractionPrompt:
    """Tests for _build_topic_extraction_prompt()."""

    def test_includes_chunk_data_in_prompt(self):
        """Prompt includes formatted chunk data."""
        chunks = [
            {"id": "chunk_0000", "start": 0.0, "end": 10.5, "text": "Hello world"},
            {"id": "chunk_0001", "start": 10.5, "end": 20.0, "text": "Test chunk"},
        ]

        prompt = _build_topic_extraction_prompt(chunks)

        assert "[chunk_0000] (0.0s - 10.5s): Hello world" in prompt
        assert "[chunk_0001] (10.5s - 20.0s): Test chunk" in prompt

    def test_includes_max_topics_instruction_when_provided(self):
        """Prompt includes max_topics instruction when specified."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]

        prompt = _build_topic_extraction_prompt(chunks, max_topics=5)

        assert "at most 5 topics" in prompt

    def test_no_max_topics_instruction_when_not_provided(self):
        """Prompt does not include max_topics when not specified."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]

        prompt = _build_topic_extraction_prompt(chunks)

        assert "at most" not in prompt


class TestParseTopicResponse:
    """Tests for _parse_topic_response()."""

    def test_parses_valid_json(self):
        """Successfully parses valid JSON response."""
        response = '[{"label": "Topic 1", "chunk_ids": ["chunk_0000"]}]'

        topics = _parse_topic_response(response)

        assert len(topics) == 1
        assert topics[0]["label"] == "Topic 1"
        assert topics[0]["chunk_ids"] == ["chunk_0000"]

    def test_strips_markdown_code_blocks(self):
        """Handles responses wrapped in markdown code blocks."""
        response = "```json\n" '[{"label": "Topic 1", "chunk_ids": []}]' "\n```"

        topics = _parse_topic_response(response)

        assert len(topics) == 1
        assert topics[0]["label"] == "Topic 1"

    def test_raises_value_error_on_invalid_json(self):
        """Raises ValueError when response is not valid JSON."""
        response = "This is not JSON"

        with pytest.raises(ValueError, match="LLM returned invalid JSON"):
            _parse_topic_response(response)

    def test_raises_value_error_on_malformed_json(self):
        """Raises ValueError when JSON is malformed."""
        response = '{"label": "Topic 1"'  # Missing closing brace

        with pytest.raises(ValueError, match="LLM returned invalid JSON"):
            _parse_topic_response(response)


class TestEstimateTokenCount:
    """Tests for _estimate_token_count()."""

    def test_estimates_tokens_correctly(self):
        """Estimates approximately 1 token per 4 characters."""
        text = "a" * 400  # 400 characters
        tokens = _estimate_token_count(text)
        assert tokens == 100  # 400 / 4 = 100

    def test_handles_empty_string(self):
        """Handles empty string."""
        assert _estimate_token_count("") == 0


class TestSegmentTopicsWithLLM:
    """Tests for segment_topics_with_llm()."""

    def test_calls_anthropic_api_successfully(self):
        """Successfully calls Anthropic API and parses response."""
        chunks = [
            {"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test chunk"},
        ]
        mock_client = mock.Mock()
        mock_response = mock.Mock()
        mock_response.content = [
            mock.Mock(text='[{"label": "Topic 1", "chunk_ids": ["chunk_0000"]}]')
        ]
        mock_client.messages.create.return_value = mock_response

        topics = segment_topics_with_llm(mock_client, chunks)

        assert len(topics) == 1
        assert topics[0]["label"] == "Topic 1"
        mock_client.messages.create.assert_called_once()

    def test_retries_on_timeout_error(self):
        """Retries API call on timeout errors."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]
        mock_client = mock.Mock()

        # First call times out, second succeeds
        # Create custom exception class with timeout in the name
        class NetworkTimeoutError(Exception):
            pass

        mock_response = mock.Mock()
        mock_response.content = [mock.Mock(text='[{"label": "T1", "chunk_ids": []}]')]

        mock_client.messages.create.side_effect = [
            NetworkTimeoutError("timeout"),
            mock_response,
        ]

        with mock.patch("videotool.llm.time.sleep"):  # Skip actual sleep
            topics = segment_topics_with_llm(mock_client, chunks)

        assert len(topics) == 1
        assert mock_client.messages.create.call_count == 2

    def test_raises_connection_error_after_max_retries(self):
        """Raises ConnectionError after exhausting retries on timeout."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]
        mock_client = mock.Mock()

        # Create custom exception class with timeout in the name
        class NetworkTimeoutError(Exception):
            pass

        mock_client.messages.create.side_effect = NetworkTimeoutError("timeout")

        with mock.patch("videotool.llm.time.sleep"):
            with pytest.raises(ConnectionError, match="timeout/network error"):
                segment_topics_with_llm(mock_client, chunks)

        # Should retry MAX_RETRIES + 1 times (initial + 2 retries = 3 total)
        assert mock_client.messages.create.call_count == 3

    def test_raises_immediately_on_non_retryable_error(self):
        """Does not retry on non-retryable errors like auth failures."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]
        mock_client = mock.Mock()

        auth_error = Exception("Invalid API key")
        mock_client.messages.create.side_effect = auth_error

        with pytest.raises(Exception, match="Invalid API key"):
            segment_topics_with_llm(mock_client, chunks)

        # Should only try once, no retries
        assert mock_client.messages.create.call_count == 1


class TestSegmentTopicsWithLocalLLM:
    """Tests for segment_topics_with_local_llm()."""

    def test_processes_small_input_in_single_batch(self):
        """Processes input that fits in context window without batching."""
        chunks = [
            {"id": "chunk_0000", "start": 0.0, "end": 5.0, "text": "Short chunk"},
        ]

        with mock.patch("videotool.llm.get_ollama_client") as mock_get_client:
            mock_client = mock.Mock()
            mock_get_client.return_value = mock_client

            mock_response = mock.Mock()
            mock_response.choices = [
                mock.Mock(
                    message=mock.Mock(content='[{"label": "T1", "chunk_ids": []}]')
                )
            ]
            mock_client.chat.completions.create.return_value = mock_response

            topics = segment_topics_with_local_llm(chunks)

        assert len(topics) == 1
        assert mock_client.chat.completions.create.call_count == 1

    def test_batches_large_input(self):
        """Batches input when it exceeds context window limit."""
        # Create many chunks to exceed MAX_INPUT_TOKENS
        chunks = [
            {
                "id": f"chunk_{i:04d}",
                "start": i * 10.0,
                "end": (i + 1) * 10.0,
                "text": "A" * 200,  # Long text to trigger batching
            }
            for i in range(50)  # 50 chunks with 200 chars each
        ]

        with mock.patch("videotool.llm.get_ollama_client") as mock_get_client:
            mock_client = mock.Mock()
            mock_get_client.return_value = mock_client

            mock_response = mock.Mock()
            mock_response.choices = [
                mock.Mock(message=mock.Mock(content='[{"label": "T", "chunk_ids": []}]'))
            ]
            mock_client.chat.completions.create.return_value = mock_response

            topics = segment_topics_with_local_llm(chunks)

        # Should have made multiple API calls (batched)
        assert mock_client.chat.completions.create.call_count > 1

    def test_raises_on_ollama_error(self):
        """Raises error when Ollama API call fails."""
        chunks = [{"id": "chunk_0000", "start": 0.0, "end": 10.0, "text": "Test"}]

        with mock.patch("videotool.llm.get_ollama_client") as mock_get_client:
            mock_client = mock.Mock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("Ollama error")

            with pytest.raises(Exception, match="Ollama error"):
                segment_topics_with_local_llm(chunks)
