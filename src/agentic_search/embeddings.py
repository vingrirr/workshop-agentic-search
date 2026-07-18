"""Jina embeddings client + pure-Python cosine similarity.

The original workshop delegated vectorization and similarity to Elasticsearch +
``langchain_community.JinaEmbeddings``. Here we call the Jina API directly and
do similarity in Python, which is plenty fast for a few hundred documents and
keeps the datasource layer free of any vector-store dependency.
"""

from __future__ import annotations

import math

import requests

from .config import Settings, load_settings

JINA_EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"


class JinaEmbedder:
    """Thin wrapper over the Jina embeddings HTTP API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout: float = 60.0,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or load_settings()
        self.api_key = api_key or settings.jina.api_key
        self.model_name = model_name or settings.jina.model_name
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input text."""

        if not self.api_key:
            raise ValueError(
                "No Jina API key configured. Set JINA_API_KEY in your .env to use "
                "semantic search (see .env.example)."
            )
        if not texts:
            return []

        response = requests.post(
            JINA_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model_name, "input": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        # Preserve input order (the API returns an "index" per embedding).
        rows = sorted(data["data"], key=lambda row: row["index"])
        return [row["embedding"] for row in rows]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
