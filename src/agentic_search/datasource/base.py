"""The swappable data-access seam.

To change the underlying datasource, subclass :class:`SearchBackend` and
implement the capabilities you need. The tools and agent loop depend only on
this interface, not on any concrete store, so swapping the backend does not
touch the rest of the project.

A backend implements whichever capabilities make sense for it:

- ``index_documents`` - ingest records (used by ``scripts/prepare_data.py``)
- ``semantic_search`` - dense/vector similarity (technique 01)
- ``execute_query``   - run a query in the backend's native language (technique 02)
- ``query_skill``     - describe that query language as a loadable skill

Capabilities a backend does not support keep the default implementation, which
raises ``NotImplementedError`` with a clear message.

The reference implementation is :class:`~agentic_search.datasource.postgres_backend.PostgresBackend`
(PostgreSQL + pgvector).
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Sequence

from ..models import Document, Skill


class SearchBackend(ABC):
    #: Human-readable backend name (used in error messages).
    name: str = "backend"

    #: The native query language accepted by :meth:`execute_query`, shown in
    #: tool descriptions (e.g. "SQL"). ``None`` if not query-capable.
    query_language: str | None = None

    def index_documents(
        self, documents: Sequence[Document], ids: Sequence[str] | None = None
    ) -> None:
        raise NotImplementedError(f"{self.name} does not support indexing")

    def semantic_search(self, query: str, k: int = 3) -> list[Document]:
        raise NotImplementedError(f"{self.name} does not support semantic search")

    def execute_query(self, query: str) -> str:
        raise NotImplementedError(f"{self.name} does not support query execution")

    def query_skill(self) -> Skill | None:
        """The progressive-disclosure skill describing this backend's query
        language, or ``None`` if the backend is not query-capable."""

        return None
