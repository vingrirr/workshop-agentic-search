#!/usr/bin/env python
"""Technique 02 - Agentic search with a database query tool (notebook 02).

The agent writes SQL from scratch and runs it against the PostgreSQL backend.
With --skill (default) it can first load the `postgres-sql` skill for guidance on
the query language - progressive disclosure without a framework.

    python scripts/run_db_query.py -q "How many sessions are on April 8th?"
    python scripts/run_db_query.py --no-skill -q "..."   # compare without the skill
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_search.agent import run_agent
from agentic_search.build import build_db_query
from agentic_search.config import load_settings
from agentic_search.datasource.postgres_backend import PostgresBackend
from agentic_search.llm import build_llm

DEFAULT_QUERY = "Which sessions should I visit to learn more about GEPA?"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", "-q", default=DEFAULT_QUERY, help="User question")
    parser.add_argument("--skill", dest="skill", action="store_true", default=True,
                        help="Give the agent the postgres-sql skill (default: on)")
    parser.add_argument("--no-skill", dest="skill", action="store_false")
    args = parser.parse_args(argv)

    settings = load_settings()
    # The query-writing agent benefits from a slightly larger model.
    llm = build_llm(model=settings.llm.mid_model, settings=settings)
    backend = PostgresBackend(settings=settings)

    system_prompt, tools = build_db_query(backend, with_skill=args.skill)
    run_agent(llm, system_prompt, tools, args.query)


if __name__ == "__main__":
    main()
