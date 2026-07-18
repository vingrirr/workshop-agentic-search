"""A minimal, transparent agent loop with tool calling.

This is the heart of the standalone project and the replacement for LangChain's
``create_agent``. There is no hidden control flow: the loop asks the model for a
response, runs any tool calls it requested, feeds the results back, and repeats
until the model answers without calling a tool (or a step limit is hit).

Set a breakpoint anywhere in :func:`run_agent` to watch the whole thing work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .llm import LLMClient


@dataclass
class Tool:
    """A tool the agent can call.

    ``parameters`` is a JSON Schema object describing the tool's arguments.
    ``func`` receives those arguments as keyword args and returns a string.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., str]

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _print_step(message: dict[str, Any]) -> None:
    """Human-readable trace of one assistant turn (mirrors the notebooks)."""

    content = (message.get("content") or "").strip()
    if content:
        print("\n=== Assistant ===")
        print(content)
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        print(f"\n--- Tool call: {fn.get('name')} ---")
        print(f"    args: {fn.get('arguments')}")


def _print_tool_result(name: str, result: str) -> None:
    print(f"\n--- Tool result: {name} ---")
    preview = result if len(result) <= 2000 else result[:2000] + "\n… (truncated)"
    print(preview)


def run_agent(
    llm: LLMClient,
    system_prompt: str,
    tools: list[Tool],
    query: str,
    *,
    max_steps: int = 10,
    verbose: bool = True,
) -> str:
    """Run the agent until it produces a final answer.

    Returns the final assistant message content.
    """

    tools_by_name = {tool.name: tool for tool in tools}
    tool_schemas = [tool.to_openai_schema() for tool in tools] or None

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    if verbose:
        print("=== User ===")
        print(query)

    for _ in range(max_steps):
        message = llm.chat(messages, tools=tool_schemas)
        # Persist the assistant turn exactly as returned so tool_call ids line up.
        messages.append(message)
        if verbose:
            _print_step(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return message.get("content") or ""

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            tool = tools_by_name.get(name)
            if tool is None:
                result = f"Error: unknown tool {name!r}"
            else:
                try:
                    result = tool.func(**args)
                except Exception as exc:  # surface tool errors back to the model
                    result = f"Error running tool {name!r}: {exc}"

            if verbose:
                _print_tool_result(name, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": result,
                }
            )

    return "(stopped: reached max steps without a final answer)"
