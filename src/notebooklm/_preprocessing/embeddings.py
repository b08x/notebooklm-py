import logging
import os
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "embeddinggemma:latest"
#: A single ``/api/embed`` call sends every text in the batch in one request;
#: against a remote/loaded Ollama host, a large batch can legitimately exceed
#: a short timeout well before anything is actually wrong. Raised from 60s
#: after a real timeout was observed mid-ingestion against a remote host, and
#: made env-configurable rather than just bumped, since the right value
#: depends on the host. See also ``IngestionService``'s batching, which caps
#: how many texts go in a single request in the first place.
DEFAULT_OLLAMA_EMBED_TIMEOUT = float(os.environ.get("OLLAMA_EMBED_TIMEOUT", "120.0"))


class EmbeddingAdapter(ABC):
    """Abstract base class for text embedding adapters."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in the same order."""


class OllamaEmbeddingAdapter(EmbeddingAdapter):
    """Embeds text via a locally running Ollama server.

    Assumes Ollama is already running as a service (the common case) and the
    embedding model has already been pulled (`ollama pull embeddinggemma`).
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.model = model or os.environ.get("EMBEDDING_MODEL", DEFAULT_OLLAMA_MODEL)
        self.base_url = base_url or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        self.timeout = timeout if timeout is not None else DEFAULT_OLLAMA_EMBED_TIMEOUT

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            resp = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(
                "Ollama embedding request failed against %s (model=%s, batch=%d texts, "
                "timeout=%.0fs): %s",
                self.base_url,
                self.model,
                len(texts),
                self.timeout,
                e,
            )
            raise RuntimeError(f"Ollama embedding request failed: {e}") from e

        embeddings = resp.json().get("embeddings")
        if embeddings is None or len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama returned {len(embeddings) if embeddings else 0} embeddings "
                f"for {len(texts)} inputs"
            )
        return embeddings
