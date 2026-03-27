"""Tests for vodtool.embeddings module."""

import os
from unittest import mock

import pytest

from vodtool.embeddings import (
    OpenAIEmbeddingProvider,
    LocalEmbeddingProvider,
    get_embedding_provider,
)


class TestOpenAIEmbeddingProvider:
    def test_raises_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY not set"):
            OpenAIEmbeddingProvider(api_key=None)

    def test_raises_if_openai_not_installed(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="openai package not installed"):
                OpenAIEmbeddingProvider()

    def test_embed_empty_list_returns_empty(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch("openai.OpenAI"):
            provider = OpenAIEmbeddingProvider()
        assert provider.embed([]) == []

    def test_embed_calls_api_and_returns_vectors(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_response = mock.Mock()
        mock_response.data = [
            mock.Mock(embedding=[0.1, 0.2, 0.3]),
            mock.Mock(embedding=[0.4, 0.5, 0.6]),
        ]
        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock_openai_cls.return_value
            mock_client.embeddings.create.return_value = mock_response
            provider = OpenAIEmbeddingProvider()
            result = provider.embed(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embeddings.create.assert_called_once_with(
            input=["hello", "world"], model="text-embedding-3-small"
        )

    def test_model_name_property(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch("openai.OpenAI"):
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        assert provider.model_name == "text-embedding-3-large"

    def test_api_failure_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock_openai_cls.return_value
            mock_client.embeddings.create.side_effect = Exception("API error")
            provider = OpenAIEmbeddingProvider()
            with pytest.raises(Exception, match="API error"):
                provider.embed(["text"])


class TestLocalEmbeddingProvider:
    def test_raises_if_sentence_transformers_not_installed(self):
        with mock.patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="sentence-transformers not installed"):
                LocalEmbeddingProvider()

    def test_embed_returns_vectors(self):
        import numpy as np

        mock_model = mock.Mock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)

        with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")
            result = provider.embed(["hello", "world"])

        assert len(result) == 2
        assert len(result[0]) == 2

    def test_embed_empty_list_returns_empty(self):
        mock_model = mock.Mock()
        with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            provider = LocalEmbeddingProvider()
        assert provider.embed([]) == []


class TestGetEmbeddingProvider:
    def test_openai_provider(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with mock.patch("openai.OpenAI"):
            provider = get_embedding_provider("openai")
        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_local_provider(self):
        mock_model = mock.Mock()
        with mock.patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            provider = get_embedding_provider("local")
        assert isinstance(provider, LocalEmbeddingProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_embedding_provider("fireworks")
