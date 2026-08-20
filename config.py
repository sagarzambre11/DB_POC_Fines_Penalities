"""
config.py
---------
Loads Azure OpenAI credentials, embedding provider settings, and application
configuration from the .env file.

Embedding provider is abstracted: set EMBEDDING_PROVIDER=azure (default) or
EMBEDDING_PROVIDER=google. Switching providers requires only .env changes — no
code changes anywhere in the application.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class AzureOpenAIConfig:
    """Azure OpenAI connection settings (LLM)."""

    ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of missing required config keys."""
        missing = []
        if not cls.ENDPOINT:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not cls.API_KEY:
            missing.append("AZURE_OPENAI_API_KEY")
        if not cls.DEPLOYMENT:
            missing.append("AZURE_OPENAI_DEPLOYMENT")
        return missing


class EmbeddingConfig:
    """
    Provider-agnostic embedding configuration.

    PROVIDER controls which backend is active:
      "azure"  — uses Azure OpenAI text-embedding-3-small (default, no extra key needed)
      "google" — uses Google text-embedding-004 (requires GOOGLE_API_KEY)

    To switch providers, update .env:
        EMBEDDING_PROVIDER=google
        GOOGLE_API_KEY=<your_key>

    No code changes are required anywhere else.
    """

    PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "azure").lower()

    # ── Azure OpenAI embedding settings (active when PROVIDER=azure) ──────────
    # Reuses the same endpoint and API key as the LLM.
    AZURE_DEPLOYMENT: str = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    AZURE_API_VERSION: str = os.getenv("AZURE_EMBEDDING_API_VERSION", "2024-02-01")

    # ── Google embedding settings (active when PROVIDER=google) ───────────────
    # Leave GOOGLE_API_KEY blank while using Azure — no errors occur.
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_MODEL: str = os.getenv("GOOGLE_EMBEDDING_MODEL", "models/text-embedding-004")

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of missing required config keys for the active provider."""
        missing = []
        if cls.PROVIDER == "google":
            if not cls.GOOGLE_API_KEY:
                missing.append("GOOGLE_API_KEY")
        elif cls.PROVIDER == "azure":
            if not AzureOpenAIConfig.ENDPOINT:
                missing.append("AZURE_OPENAI_ENDPOINT")
            if not AzureOpenAIConfig.API_KEY:
                missing.append("AZURE_OPENAI_API_KEY")
            if not cls.AZURE_DEPLOYMENT:
                missing.append("AZURE_EMBEDDING_DEPLOYMENT")
        else:
            missing.append(f"EMBEDDING_PROVIDER (unknown value: '{cls.PROVIDER}', use 'azure' or 'google')")
        return missing

    @classmethod
    def provider_display(cls) -> str:
        """Human-readable provider label for UI display."""
        if cls.PROVIDER == "google":
            return f"Google · {cls.GOOGLE_MODEL}"
        return f"Azure OpenAI · {cls.AZURE_DEPLOYMENT}"


class AppConfig:
    """General application settings."""

    GRC_INVENTORY_PATH: str = os.getenv(
        "GRC_INVENTORY_PATH", "docs/grc_inventory.xlsx"
    )
    GRC_SHEET_NAME: str = os.getenv("GRC_SHEET_NAME", "grc_control_inv1")

    # ── LLM generation parameters ─────────────────────────────────────────────
    # gpt-5-mini is a REASONING model: max_completion_tokens covers reasoning + output.
    # Values below 16,000 cause the model to exhaust tokens on reasoning → empty output.
    MAX_TOKENS_EXTRACTION: int = 25000   # reasoning + structured JSON output
    MAX_TOKENS_COMPARISON: int = 25000   # reasoning + batch gap analysis JSON
    MAX_TOKENS_SUMMARY: int = 16000      # reasoning + overall assessment JSON

    # ── RAG / Vector Store settings ───────────────────────────────────────────
    VECTOR_DB_PATH: str = os.getenv("VECTOR_DB_PATH", ".chromadb")
    # Controls retrieved per enforcement theme before deduplication
    RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "8"))
    # Maximum unique controls passed to LLM after cross-theme deduplication
    MAX_RETRIEVED_CONTROLS: int = int(os.getenv("MAX_RETRIEVED_CONTROLS", "15"))

    # ── Coverage classification labels ────────────────────────────────────────
    # These must exactly match the labels the LLM is instructed to output
    # in comparator.py BATCH_SYSTEM_PROMPT.
    COVERAGE_LABELS = [
        "Covered",
        "Partially Covered",
        "Potential Gap",
        "Insufficient Evidence",
    ]

    # ── Emoji map for UI display ──────────────────────────────────────────────
    COVERAGE_EMOJI = {
        "Covered":               "✅",
        "Partially Covered":     "🟡",
        "Potential Gap":         "🔴",
        "Insufficient Evidence": "❓",
    }

    COVERAGE_COLOR = {
        "Covered":               "#d4edda",
        "Partially Covered":     "#fff3cd",
        "Potential Gap":         "#f8d7da",
        "Insufficient Evidence": "#e2e3e5",
    }
