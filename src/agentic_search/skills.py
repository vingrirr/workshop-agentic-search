"""Agent Skills with progressive disclosure (technique 02).

Skills keep detailed, situational instructions *out* of the system prompt until
they are needed. We advertise only a short description of each skill up front,
and the agent calls the ``load_skill`` tool to pull the full content into its
context on demand.

This re-implements the notebook's ``SkillMiddleware`` without LangChain: instead
of middleware, :func:`skills_addendum` returns text to append to the system
prompt, and :func:`make_load_skill_tool` returns the loader tool. The skills
themselves come from the datasource backend (see ``SearchBackend.query_skill``),
so the guidance always matches the active query language.
"""

from __future__ import annotations

from .agent import Tool
from .models import Skill


def load_skill(skills: list[Skill], skill_name: str) -> str:
    """Load the full content of a skill into the agent's context."""

    for skill in skills:
        if skill["name"] == skill_name:
            return f"Loaded skill: {skill_name}\n\n{skill['content']}"
    available = ", ".join(s["name"] for s in skills) or "(none)"
    return f"Skill '{skill_name}' not found. Available skills: {available}"


def make_load_skill_tool(skills: list[Skill]) -> Tool:
    def _load_skill(skill_name: str) -> str:
        return load_skill(skills, skill_name)

    return Tool(
        name="load_skill",
        description=(
            "Load the full content of a skill into your context. Use this when you "
            "need detailed instructions for a specific type of request."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "The name of the skill to load (e.g. 'postgres-sql').",
                }
            },
            "required": ["skill_name"],
        },
        func=_load_skill,
    )


def skills_addendum(skills: list[Skill]) -> str:
    """Text appended to the system prompt to advertise the available skills."""

    listed = "\n".join(f"- **{s['name']}**: {s['description']}" for s in skills)
    return (
        "\n\n## Available Skills\n\n"
        f"{listed}\n\n"
        "Use the load_skill tool when you need detailed information about handling "
        "a specific type of request."
    )
