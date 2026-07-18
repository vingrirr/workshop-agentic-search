"""Assemble each technique into a (system_prompt, tools) pair.

The scripts under ``scripts/`` create an :class:`~agentic_search.llm.LLMClient`,
call one of these builders, and hand both to
:func:`~agentic_search.agent.run_agent`. Keeping assembly here (rather than
hidden in a framework) means each script stays short and readable.
"""

from __future__ import annotations

from .agent import Tool
from .datasource.base import SearchBackend
from .prompts import load_fs_prompt, load_prompt
from .skills import make_load_skill_tool, skills_addendum
from .tools import make_query_tool, make_semantic_search_tool, make_shell_tool


def build_vanilla_search(backend: SearchBackend) -> tuple[str, list[Tool]]:
    """Technique 01: one semantic search tool over the backend."""

    system_prompt = load_prompt("system_prompt_db")
    return system_prompt, [make_semantic_search_tool(backend)]


def build_db_query(
    backend: SearchBackend, *, with_skill: bool = True
) -> tuple[str, list[Tool]]:
    """Technique 02: a general-purpose query tool, optionally with a query skill.

    The skill (and its query-language dialect) comes from the backend, so this
    works unchanged if you swap the datasource.
    """

    system_prompt = load_prompt("system_prompt_db")
    tools: list[Tool] = [make_query_tool(backend)]

    skill = backend.query_skill()
    if with_skill and skill is not None:
        reminder = (
            f" If you need to execute a query, use the {skill['name']} skill to "
            "write it before calling the execute_sql_query tool. If a query returns "
            f"an error, use the {skill['name']} skill again to write a corrected query."
        )
        system_prompt = system_prompt + skills_addendum([skill]) + reminder
        tools.append(make_load_skill_tool([skill]))

    return system_prompt, tools


def build_shell_search(*, use_jina: bool = False) -> tuple[str, list[Tool]]:
    """Technique 03: a shell tool over the exported session files."""

    name = "system_prompt_fs_jina_grep" if use_jina else "system_prompt_fs"
    system_prompt = load_fs_prompt(name)
    return system_prompt, [make_shell_tool()]
