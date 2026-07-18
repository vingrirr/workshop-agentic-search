"""Central configuration for the standalone agentic-search project.

Loads settings from environment variables (via a ``.env`` file) and resolves
project paths from the location of this file, so the code behaves the same
whether it is launched from a script, a test, or the VS Code debugger -
regardless of the current working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root = two levels up from this file (src/agentic_search/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
SESSIONS_PATH = DATA_DIR / "sessions.json"
SESSION_DATA_DIR = DATA_DIR / "session_data"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Load .env from the project root. override=True mirrors the original notebooks.
load_dotenv(PROJECT_ROOT / ".env", override=True)


@dataclass(frozen=True)
class LLMSettings:
    """Connection details for an OpenAI-compatible chat endpoint (e.g. LiteLLM)."""

    api_base: str | None = None
    api_key: str | None = None
    # A small model is enough for simple retrieval; the query-writing agent uses
    # a slightly larger one. Both names are passed straight through to the gateway.
    small_model: str = "llm-gateway/gpt-5.4-nano"
    mid_model: str = "llm-gateway/gpt-5.4-mini"
    temperature: float = 0.5


@dataclass(frozen=True)
class PostgresSettings:
    """Connection details for the PostgreSQL datasource."""

    # libpq connection string / DATABASE_URL, e.g.
    # "postgresql://user:pass@localhost:5432/dbname". Empty -> libpq defaults
    # (PGHOST / PGUSER / PGDATABASE ... environment variables).
    dsn: str = ""
    table: str = "conference_schedule"
    # Embedding column dimension. None -> detected from the model at index time.
    embedding_dim: int | None = None


@dataclass(frozen=True)
class JinaSettings:
    """Connection details for Jina embeddings (used by semantic search)."""

    api_key: str | None = None
    model_name: str = "jina-embeddings-v5-text-small"


@dataclass(frozen=True)
class Settings:
    llm: LLMSettings
    postgres: PostgresSettings
    jina: JinaSettings

    # Paths (constants above, exposed here for convenience / overriding in tests).
    sessions_path: Path = SESSIONS_PATH
    session_data_dir: Path = SESSION_DATA_DIR
    prompts_dir: Path = PROMPTS_DIR


def load_settings() -> Settings:
    """Build a :class:`Settings` object from the current environment."""

    embedding_dim = os.getenv("EMBEDDING_DIM")
    return Settings(
        llm=LLMSettings(
            api_base=os.getenv("LITELLM_API_BASE"),
            api_key=os.getenv("LITELLM_API_KEY"),
            small_model=os.getenv("LLM_SMALL_MODEL", LLMSettings.small_model),
            mid_model=os.getenv("LLM_MID_MODEL", LLMSettings.mid_model),
            temperature=float(os.getenv("LLM_TEMPERATURE", LLMSettings.temperature)),
        ),
        postgres=PostgresSettings(
            dsn=os.getenv("DATABASE_URL", ""),
            table=os.getenv("PG_TABLE", PostgresSettings.table),
            embedding_dim=int(embedding_dim) if embedding_dim else None,
        ),
        jina=JinaSettings(
            api_key=os.getenv("JINA_API_KEY"),
            model_name=os.getenv("JINA_MODEL", JinaSettings.model_name),
        ),
    )
