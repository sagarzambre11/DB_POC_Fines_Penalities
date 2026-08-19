"""
config.py
---------
Loads Azure OpenAI credentials and application settings from the .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class AzureOpenAIConfig:
    """Azure OpenAI connection settings."""

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


class AppConfig:
    """General application settings."""

    GRC_INVENTORY_PATH: str = os.getenv(
        "GRC_INVENTORY_PATH", "docs/grc_inventory.xlsx"
    )
    GRC_SHEET_NAME: str = os.getenv("GRC_SHEET_NAME", "grc_control_inv1")

    # LLM generation parameters
    MAX_TOKENS_EXTRACTION: int = 4096
    MAX_TOKENS_COMPARISON: int = 16384  # gap analysis output is large (one entry per inventory item)
    TEMPERATURE: float = 0.0  # deterministic for compliance use-cases

    # Coverage classification labels
    COVERAGE_LABELS = [
        "Covered",
        "Partially Covered",
        "Policy-Only Coverage",
        "Potential Control Gap",
        "Insufficient Evidence",
    ]

    # Emoji map for UI display
    COVERAGE_EMOJI = {
        "Covered": "✅",
        "Partially Covered": "🟡",
        "Policy-Only Coverage": "📄",
        "Potential Control Gap": "🔴",
        "Insufficient Evidence": "❓",
    }

    COVERAGE_COLOR = {
        "Covered": "#d4edda",
        "Partially Covered": "#fff3cd",
        "Policy-Only Coverage": "#cce5ff",
        "Potential Control Gap": "#f8d7da",
        "Insufficient Evidence": "#e2e3e5",
    }
