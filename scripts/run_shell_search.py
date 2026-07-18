#!/usr/bin/env python
"""Technique 03 - Agentic search with a shell tool (notebook 03).

The agent runs shell commands (grep / find / cat) over the exported session
files, and with --jina it is told about the jina-grep CLI for semantic search.
Run `python scripts/prepare_data.py` first so data/session_data/ exists.

WARNING: the shell tool runs arbitrary commands with no sandboxing.

    python scripts/run_shell_search.py -q "Are there any sessions about GEPA?"
    python scripts/run_shell_search.py --jina -q "sessions on regulatory constraints"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_search.agent import run_agent
from agentic_search.build import build_shell_search
from agentic_search.config import load_settings
from agentic_search.llm import build_llm

DEFAULT_QUERY = "Which sessions discuss handling regulatory constraints?"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", "-q", default=DEFAULT_QUERY, help="User question")
    parser.add_argument("--jina", action="store_true",
                        help="Tell the agent about the jina-grep CLI (semantic search)")
    args = parser.parse_args(argv)

    settings = load_settings()
    llm = build_llm(model=settings.llm.small_model, settings=settings)

    system_prompt, tools = build_shell_search(use_jina=args.jina)
    run_agent(llm, system_prompt, tools, args.query)


if __name__ == "__main__":
    main()
