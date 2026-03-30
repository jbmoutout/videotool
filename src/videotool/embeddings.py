"""Embedding provider abstraction for videotool.

Defines the EmbeddingProvider Protocol and two implementations:
- OpenAIEmbeddingProvider: uses OpenAI text-embedding-3-small (cloud, MVP default)
- LocalEmbeddingProvider: uses sentence-transformers (local, future privacy mode)
"""

import os
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, returning a list of float vectors."""
        ...

    @property
    def model_name(self) -> str:
        """Identifier for the model used (stored in embeddings.sqlite)."""
        ...


class OpenAIEmbeddingProvider:
    """Embeds text using OpenAI's text-embedding-3-small API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        try:
            import openai
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]


class LocalEmbeddingProvider:
    """Embeds text using a local sentence-transformers model."""

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            )
        self._model_name = model
        self._model = SentenceTransformer(model)

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vectors]


def get_embedding_provider(
    provider: str = "openai",
    model: Optional[str] = None,
) -> EmbeddingProvider:
    """
    Return an EmbeddingProvider by name.

    Args:
        provider: "openai" or "local"
        model: Optional model override

    Returns:
        An EmbeddingProvider instance

    Raises:
        ValueError: if provider name is unknown
    """
    if provider == "openai":
        kwargs = {"model": model} if model else {}
        return OpenAIEmbeddingProvider(**kwargs)
    elif provider == "local":
        kwargs = {"model": model} if model else {}
        return LocalEmbeddingProvider(**kwargs)
    else:
        raise ValueError(f"Unknown embedding provider: {provider!r}. Choose 'openai' or 'local'.")
