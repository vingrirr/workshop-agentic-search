"""Tool factories for the three search techniques.

Each factory returns a :class:`~agentic_search.agent.Tool`. The retrieval tools
close over a :class:`~agentic_search.datasource.base.SearchBackend`, so swapping
the datasource does not change the tools or the agent.
"""

from __future__ import annotations

import subprocess

from .agent import Tool
from .datasource.base import SearchBackend


def make_semantic_search_tool(backend: SearchBackend, *, k: int = 3) -> Tool:
    """Technique 01: semantic search over the backend (vanilla agentic RAG)."""

    def semantic_search_conference_sessions(query: str) -> str:
        docs = backend.semantic_search(query, k=k)
        return "\n\n".join(
            f"**{doc.metadata.get('type')} by {doc.metadata.get('speakers')}**: "
            f"{doc.metadata.get('title')}\nDescription:{doc.page_content}"
            for doc in docs
        )

    return Tool(
        name="semantic_search_conference_sessions",
        description=(
            "Runs a semantic search query to find conference sessions by concept "
            "or topic. Use it when the user asks about a theme, idea, or subject "
            "rather than an exact keyword.\n\n"
            "Args:\n  query: The topic or concept to search for."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The topic or concept used as the search query.",
                }
            },
            "required": ["query"],
        },
        func=semantic_search_conference_sessions,
    )


def make_query_tool(backend: SearchBackend) -> Tool:
    """Technique 02: let the agent write a query in the backend's native language."""

    language = backend.query_language or "database"
    skill = backend.query_skill()
    skill_hint = (
        f"Always use the {skill['name']} skill to write the {language} query before "
        "calling this tool.\n"
        if skill is not None
        else ""
    )

    def execute_query(query: str) -> str:
        return backend.execute_query(query)

    return Tool(
        name="execute_sql_query",
        description=(
            f"Execute a read-only {language} query against the conference_schedule "
            "table and return the result as CSV.\n"
            f"{skill_hint}\n"
            "Args:\n  query: The SQL query to execute."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": f"The {language} query to execute.",
                }
            },
            "required": ["query"],
        },
        func=execute_query,
    )


def make_shell_tool(*, timeout: float = 60.0) -> Tool:
    """Technique 03: run shell commands (grep / find / cat / jina-grep).

    WARNING: this runs arbitrary shell commands with no sandboxing, exactly like
    the notebook's ShellTool. Only use it in an environment you are comfortable
    giving an LLM shell access to.
    """

    def terminal(command: str) -> str:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout}s"
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return output or "(no output)"

    return Tool(
        name="terminal",
        description=(
            "Run a shell command on the host and return its stdout/stderr. Use "
            "commands like grep, find, cat, ls (and jina-grep for semantic search) "
            "to explore and read the session files.\n\n"
            "Args:\n  command: A single shell command to run."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                }
            },
            "required": ["command"],
        },
        func=terminal,
    )
