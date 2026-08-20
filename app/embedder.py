"""
app/embedder.py
---------------
Provider-agnostic embedding layer for the RAG pipeline.

Supports two embedding backends, switchable via EMBEDDING_PROVIDER in .env:
  "azure"  — Azure OpenAI text-embedding-3-small (default, no extra key needed)
  "google" — Google text-embedding-004 (requires GOOGLE_API_KEY)

All downstream code (vector_store.py, retriever.py) calls only:
  get_embedder().embed_documents(texts)  → list[list[float]]
  get_embedder().embed_query(text)       → list[float]

No URL formation, no endpoint juggling, no provider-specific logic leaks out.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from config import AzureOpenAIConfig, EmbeddingConfig

# ---------------------------------------------------------------------------
# Abstract base — the contract every provider must satisfy
# ---------------------------------------------------------------------------

class BaseEmbedder(ABC):
    """Abstract embedding provider interface."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of documents for indexing (RETRIEVAL_DOCUMENT intent).

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query string for retrieval (RETRIEVAL_QUERY intent).

        Args:
            text: The query string to embed.

        Returns:
            Single embedding vector.
        """
        ...

    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding vector dimensionality."""
        ...


# ---------------------------------------------------------------------------
# Azure OpenAI Embedder
# ---------------------------------------------------------------------------

class AzureEmbedder(BaseEmbedder):
    """
    Embedding provider using Azure OpenAI text-embedding-3-small.

    Uses the same endpoint and API key as the LLM — no additional credentials
    required. Handles both the standard Azure endpoint and the
    services.ai.azure.com (OpenAI-compatible) endpoint automatically.
    """

    def __init__(self) -> None:
        self._client = self._build_client()
        self._deployment = EmbeddingConfig.AZURE_DEPLOYMENT

    def _build_client(self):
        """Build the correct OpenAI client for the configured Azure endpoint."""
        from openai import AzureOpenAI, OpenAI

        endpoint = AzureOpenAIConfig.ENDPOINT.rstrip("/")
        api_key = AzureOpenAIConfig.API_KEY

        # services.ai.azure.com uses the OpenAI-compatible surface (/openai/v1/)
        if "services.ai.azure.com" in endpoint:
            return OpenAI(
                base_url=f"{endpoint}/openai/v1/",
                api_key=api_key,
            )

        # Standard Azure OpenAI endpoint
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=EmbeddingConfig.AZURE_API_VERSION,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts for indexing."""
        if not texts:
            return []
        # Azure OpenAI embedding — batch up to 2048 inputs per call
        response = self._client.embeddings.create(
            model=self._deployment,
            input=texts,
        )
        # Sort by index to preserve input order
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self.embed_documents([text])[0]

    def dimensions(self) -> int:
        """text-embedding-3-small produces 1536-dimensional vectors."""
        return 1536


# ---------------------------------------------------------------------------
# Google Generative AI Embedder
# ---------------------------------------------------------------------------

class GoogleEmbedder(BaseEmbedder):
    """
    Embedding provider using Google text-embedding-004 via google-generativeai.

    Uses task_type distinction for optimal retrieval quality:
      RETRIEVAL_DOCUMENT — for controls being indexed
      RETRIEVAL_QUERY    — for enforcement themes being searched

    This asymmetric embedding is specifically trained for retrieval and
    significantly outperforms generic embeddings for this use case.

    Requires: GOOGLE_API_KEY set in .env and EMBEDDING_PROVIDER=google
    """

    def __init__(self) -> None:
        # Lazy import — only loaded when PROVIDER=google, no ImportError when
        # google-generativeai is not installed and PROVIDER=azure
        try:
            import google.generativeai as genai
            self._genai = genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai package is required for Google embeddings. "
                "Run: pip install google-generativeai"
            ) from exc

        self._genai.configure(api_key=EmbeddingConfig.GOOGLE_API_KEY)
        self._model = EmbeddingConfig.GOOGLE_MODEL

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed document texts for indexing using RETRIEVAL_DOCUMENT task type.
        Google's API accepts a list of strings natively.
        """
        if not texts:
            return []
        result = self._genai.embed_content(
            model=self._model,
            content=texts,
            task_type="RETRIEVAL_DOCUMENT",
        )
        embeddings = result.get("embedding", [])
        # When content is a list, result['embedding'] is a list of lists
        if embeddings and isinstance(embeddings[0], float):
            # Single text returned as flat list — wrap it
            return [embeddings]
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """
        Embed a query string using RETRIEVAL_QUERY task type.
        This produces vectors optimised for finding relevant documents.
        """
        result = self._genai.embed_content(
            model=self._model,
            content=text,
            task_type="RETRIEVAL_QUERY",
        )
        return result.get("embedding", [])

    def dimensions(self) -> int:
        """text-embedding-004 produces 768-dimensional vectors by default."""
        return 768


# ---------------------------------------------------------------------------
# Factory — the single entry point for all embedding operations
# ---------------------------------------------------------------------------

_embedder_instance: BaseEmbedder | None = None


def get_embedder() -> BaseEmbedder:
    """
    Return the active embedding provider (singleton per process).

    Provider is determined by EMBEDDING_PROVIDER in .env:
      "azure"  → AzureEmbedder (default)
      "google" → GoogleEmbedder

    Raises:
        RuntimeError: If required config for the active provider is missing.
        ValueError:   If EMBEDDING_PROVIDER is set to an unknown value.
    """
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance

    # Validate config before attempting to construct
    missing = EmbeddingConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing embedding configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    provider = EmbeddingConfig.PROVIDER
    if provider == "azure":
        _embedder_instance = AzureEmbedder()
    elif provider == "google":
        _embedder_instance = GoogleEmbedder()
    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER: '{provider}'. "
            "Valid values: 'azure', 'google'."
        )

    return _embedder_instance


def reset_embedder() -> None:
    """
    Reset the singleton embedder instance.
    Useful when config changes at runtime (e.g. in tests).
    """
    global _embedder_instance
    _embedder_instance = None


# ---------------------------------------------------------------------------
# Control text formatter — shared by embedder and vector store
# ---------------------------------------------------------------------------

def format_control_for_embedding(control: dict) -> str:
    """
    Format a GRC control dict as a rich text string optimised for embedding.

    Includes the most semantically informative fields:
    - control_name + control_objective: the policy intent (what it requires)
    - control_description: the operational mechanism (how it works)
    - regulatory_domain + process: context for domain-specific retrieval

    Args:
        control: A single control dict from inventory.load_inventory().

    Returns:
        Formatted string ready for embedding.
    """
    parts = [
        f"{control.get('control_name', '')}",
    ]
    objective = control.get("control_objective", "").strip()
    if objective:
        parts.append(f"Objective: {objective}")

    description = control.get("control_description", "").strip()
    if description:
        parts.append(f"Mechanism: {description}")

    domain = control.get("regulatory_domain", "").strip()
    process = control.get("process", "").strip()
    if domain or process:
        context_parts = []
        if domain:
            context_parts.append(f"Domain: {domain}")
        if process:
            context_parts.append(f"Process: {process}")
        parts.append(". ".join(context_parts))

    return ". ".join(p for p in parts if p)
