"""Small framework-free data structures shared across the project."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class Document:
    """A single retrievable record.

    Mirrors the shape the original workshop relied on (``page_content`` is the
    text that gets embedded / searched; ``metadata`` holds structured fields),
    but without depending on ``langchain_core``.
    """

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill(TypedDict):
    """A skill that can be progressively disclosed to the agent (technique 02).

    Only the ``description`` is shown up front (in the system prompt); the full
    ``content`` is pulled in on demand via the ``load_skill`` tool. A datasource
    backend advertises its query-language skill through
    :meth:`~agentic_search.datasource.base.SearchBackend.query_skill`.
    """

    name: str  # unique identifier
    description: str  # 1-2 sentence summary shown in the system prompt
    content: str  # full instructions, loaded on demand
