#!/usr/bin/env python
"""Prepare the dataset (replacement for notebook 00_prepare_data).

Two independent outputs:
1. Indexes one row per session into a PostgreSQL table (with Jina embeddings in
   a pgvector column, so semantic search works).
2. Exports one markdown file per session under data/session_data/ (for the
   shell-tool technique).

Examples:
    python scripts/prepare_data.py                 # index (with embeddings) + export
    python scripts/prepare_data.py --no-embeddings # index without embeddings (offline)
    python scripts/prepare_data.py --no-index      # only export files
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``import agentic_search`` work when running this file directly (no install).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_search import dataset
from agentic_search.datasource.filesystem import export_records_by_type
from agentic_search.datasource.postgres_backend import PostgresBackend


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", dest="index", action="store_true", default=None,
                        help="Index sessions into PostgreSQL (default: on)")
    parser.add_argument("--no-index", dest="index", action="store_false")
    parser.add_argument("--export", dest="export", action="store_true", default=None,
                        help="Export markdown files to data/session_data/ (default: on)")
    parser.add_argument("--no-export", dest="export", action="store_false")
    parser.add_argument("--embeddings", dest="embeddings", action="store_true", default=None,
                        help="Fetch Jina embeddings while indexing (default: on)")
    parser.add_argument("--no-embeddings", dest="embeddings", action="store_false")
    args = parser.parse_args(argv)

    do_index = True if args.index is None else args.index
    do_export = True if args.export is None else args.export
    with_embeddings = True if args.embeddings is None else args.embeddings

    records = dataset.load_records()
    print(f"Loaded {len(records)} sessions")

    if do_index:
        documents = [dataset.record_to_document(r) for r in records]
        ids = [dataset.stable_id(r) for r in records]
        backend = PostgresBackend()
        backend.index_documents(documents, ids, with_embeddings=with_embeddings)
        note = "with embeddings" if with_embeddings else "without embeddings"
        print(f"Indexed {len(documents)} sessions into table {backend.table!r} ({note})")

    if do_export:
        root = export_records_by_type(records)
        print(f"Wrote {len(records)} files under {root.resolve()}")


if __name__ == "__main__":
    main()
