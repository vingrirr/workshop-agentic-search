#!/usr/bin/env python
"""Technique 01 - Vanilla agentic search (replacement for notebook 01).

The agent has a single semantic search tool over the PostgreSQL backend. Good
for simple, concept-level questions. Set a breakpoint in agentic_search/agent.py
(run_agent) to watch each tool call.

    python scripts/run_vanilla_search.py -q "Which sessions cover agent memory?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_search.agent import run_agent
from agentic_search.build import build_vanilla_search
from agentic_search.config import load_settings
from agentic_search.datasource.postgres_backend import PostgresBackend
from agentic_search.llm import build_llm

DEFAULT_QUERY = "Which sessions discuss regulatory constraints in AI systems?"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", "-q", default=DEFAULT_QUERY, help="User question")
    args = parser.parse_args(argv)

    settings = load_settings()
    llm = build_llm(model=settings.llm.small_model, settings=settings)
    backend = PostgresBackend(settings=settings)

    system_prompt, tools = build_vanilla_search(backend)
    run_agent(llm, system_prompt, tools, args.query)


if __name__ == "__main__":
    main()
