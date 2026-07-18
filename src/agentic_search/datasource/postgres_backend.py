"""Reference datasource backend built on PostgreSQL (+ pgvector).

This is the primary backend for the standalone project.

- ``execute_query`` runs read-only **SQL**, which is the "write a query from
  scratch" (heuristic search) technique from notebook 02. This is the main
  workhorse for structured / heuristic questions.
- ``semantic_search`` uses the **pgvector** extension: embeddings are stored in a
  ``vector`` column and ranked with the ``<=>`` cosine-distance operator. If you
  index without embeddings (``--no-embeddings``), only ``execute_query`` works.

Only dependency beyond the standard library is ``psycopg`` (v3). Vectors are
sent as text literals cast with ``::vector``, so the ``pgvector`` Python adapter
is not required - just the extension in the database.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

from ..config import Settings, load_settings
from ..embeddings import JinaEmbedder
from ..models import Document, Skill
from .base import SearchBackend

# Structured columns exposed to the SQL query tool. Keep this in sync with the
# schema description in prompts/system_prompt_db.md.
_COLUMNS = ["title", "description", "day", "time", "room", "type", "track", "speakers"]

# Progressive-disclosure skill describing this backend's query language (loaded
# on demand by the agent in technique 02).
_POSTGRES_SQL_SKILL: Skill = {
    "name": "postgres-sql",
    "description": (
        "Write PostgreSQL SQL to query the conference_schedule table: filtering "
        "rows, case-insensitive text matching with ILIKE, counting and aggregating."
    ),
    "content": """
# PostgreSQL SQL

Write SQL queries against the `conference_schedule` table in PostgreSQL.

## Table

`conference_schedule(title, description, day, time, room, type, track, speakers, text)`

- `text` is the title plus description (what semantic search embeds). Use it for
  free-text matching.
- All content columns are `text`.

## Critical Syntax Rules

### String literals use single quotes

PostgreSQL uses **single quotes** for string literals: `WHERE day = 'April 8'`.
Double quotes are for identifiers (column/table names), not string values.

### Case-insensitive matching: use ILIKE

Plain `LIKE` is **case-sensitive** in PostgreSQL. For "contains, any case" use
`ILIKE`: `WHERE text ILIKE '%gepa%'`. `%` matches zero or more characters, `_`
matches exactly one.

### Comparison & logic

- `=`, `<>` (or `!=`), `<`, `<=`, `>`, `>=`
- `AND`, `OR`, `NOT`, `IN (...)`, `IS NULL`, `IS NOT NULL`

### Counting & aggregation

- `SELECT COUNT(*) FROM conference_schedule WHERE day = 'April 8'`
- `SELECT type, COUNT(*) FROM conference_schedule GROUP BY type`

### Other

- Always add `LIMIT` when you only need a few rows.
- Select specific columns rather than `*`, and avoid the long `description` /
  `text` columns unless you need them, to keep results small.

## Examples

```sql
SELECT title, day, time, room, speakers
FROM conference_schedule
WHERE text ILIKE '%GEPA%'
LIMIT 5;
```

```sql
SELECT COUNT(*) AS count
FROM conference_schedule
WHERE day = 'April 8';
```
""",
}


def _vector_literal(vector: Sequence[float]) -> str:
    """Format a vector as a pgvector text literal, e.g. ``[0.1,0.2,0.3]``."""

    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PostgresBackend(SearchBackend):
    name = "postgres"
    query_language = "SQL"

    def __init__(
        self,
        *,
        dsn: str | None = None,
        table: str | None = None,
        embedder: JinaEmbedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or load_settings()
        # An empty conninfo lets libpq fall back to PG* environment variables.
        self.dsn = dsn if dsn is not None else settings.postgres.dsn
        self.table = table or settings.postgres.table
        self._embedder = embedder or JinaEmbedder(settings=settings)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn or "")

    def query_skill(self) -> Skill | None:
        return _POSTGRES_SQL_SKILL

    # -- ingestion ---------------------------------------------------------

    def index_documents(
        self,
        documents: Sequence[Document],
        ids: Sequence[str] | None = None,
        *,
        with_embeddings: bool = True,
    ) -> None:
        """(Re)create the table and insert the documents.

        If ``with_embeddings`` is True, embeddings for every document are fetched
        from Jina and stored in a pgvector column so :meth:`semantic_search`
        works (requires the ``vector`` extension).
        """

        ids = list(ids) if ids is not None else [str(i) for i in range(len(documents))]
        if len(ids) != len(documents):
            raise ValueError("ids and documents must have the same length")

        vectors: list[list[float]] = []
        if with_embeddings:
            vectors = self._embedder.embed([doc.page_content for doc in documents])

        col_defs = ", ".join(f'"{c}" text' for c in _COLUMNS)
        insert_cols = ", ".join(f'"{c}"' for c in _COLUMNS)

        with self._connect() as conn:
            with conn.cursor() as cur:
                if with_embeddings:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

                cur.execute(f"DROP TABLE IF EXISTS {self.table}")
                if with_embeddings:
                    dim = len(vectors[0])
                    cur.execute(
                        f"CREATE TABLE {self.table} "
                        f"(id text PRIMARY KEY, {col_defs}, text text, "
                        f"embedding vector({dim}))"
                    )
                    insert_sql = (
                        f"INSERT INTO {self.table} (id, {insert_cols}, text, embedding) "
                        f"VALUES (%s, {', '.join(['%s'] * len(_COLUMNS))}, %s, %s::vector)"
                    )
                    rows = [
                        (
                            doc_id,
                            *[doc.metadata.get(c, "") for c in _COLUMNS],
                            doc.page_content,
                            _vector_literal(vec),
                        )
                        for doc_id, doc, vec in zip(ids, documents, vectors)
                    ]
                else:
                    cur.execute(
                        f"CREATE TABLE {self.table} "
                        f"(id text PRIMARY KEY, {col_defs}, text text)"
                    )
                    insert_sql = (
                        f"INSERT INTO {self.table} (id, {insert_cols}, text) "
                        f"VALUES (%s, {', '.join(['%s'] * len(_COLUMNS))}, %s)"
                    )
                    rows = [
                        (
                            doc_id,
                            *[doc.metadata.get(c, "") for c in _COLUMNS],
                            doc.page_content,
                        )
                        for doc_id, doc in zip(ids, documents)
                    ]

                cur.executemany(insert_sql, rows)
            conn.commit()

    # -- retrieval ---------------------------------------------------------

    def semantic_search(self, query: str, k: int = 3) -> list[Document]:
        query_literal = _vector_literal(self._embedder.embed_query(query))
        select_cols = ", ".join(f'"{c}"' for c in _COLUMNS)
        try:
            with self._connect() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"SELECT {select_cols}, text "
                        f"FROM {self.table} "
                        f"ORDER BY embedding <=> %s::vector LIMIT %s",
                        (query_literal, k),
                    )
                    rows = cur.fetchall()
        except psycopg.errors.UndefinedColumn as exc:
            raise RuntimeError(
                "No embedding column found. Run `python scripts/prepare_data.py` "
                "with a JINA_API_KEY set (and the pgvector extension available) to "
                "build the semantic search index."
            ) from exc

        return [
            Document(
                page_content=row["text"],
                metadata={c: row[c] for c in _COLUMNS},
            )
            for row in rows
        ]

    def execute_query(self, query: str) -> str:
        """Run a read-only SQL query and return the result as CSV text."""

        try:
            with self._connect() as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute(query)
                    headers = [d.name for d in cur.description] if cur.description else []
                    rows = cur.fetchall() if cur.description else []
        except Exception as exc:  # return the error so the agent can self-correct
            return f"Error executing SQL query: {exc}"

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        if headers:
            writer.writerow(headers)
        writer.writerows(rows)
        return buffer.getvalue()
