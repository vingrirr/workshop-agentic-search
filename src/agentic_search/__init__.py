"""Standalone, framework-free implementation of the Agentic Search workshop.

The original workshop was a set of Jupyter notebooks built on LangChain +
Elasticsearch. This package re-implements the same three search techniques
with no agent framework and no Elasticsearch, so the whole agent loop is
plain, debuggable Python:

- a transparent agent loop over an OpenAI-compatible chat endpoint (``agent``)
- a swappable data-access layer (``datasource``) with a PostgreSQL + pgvector
  reference backend
- the three techniques assembled in ``build`` and driven by ``scripts/``
"""

from __future__ import annotations

from .agent import Tool, run_agent
from .models import Document

__all__ = ["Document", "Tool", "run_agent"]
__version__ = "0.1.0"
