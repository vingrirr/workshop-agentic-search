"""Load system prompts from the top-level ``prompts/`` directory."""

from __future__ import annotations

from pathlib import Path

from .config import PROMPTS_DIR, SESSION_DATA_DIR

#: Token used inside the filesystem prompts, replaced at load time with the real
#: (absolute) data directory so the shell agent works regardless of cwd.
SESSION_DATA_DIR_TOKEN = "__SESSION_DATA_DIR__"


def load_prompt(name: str, *, prompts_dir: Path = PROMPTS_DIR) -> str:
    if not name.endswith(".md"):
        name += ".md"
    return (Path(prompts_dir) / name).read_text(encoding="utf-8")


def load_fs_prompt(
    name: str,
    *,
    session_data_dir: Path = SESSION_DATA_DIR,
    prompts_dir: Path = PROMPTS_DIR,
) -> str:
    """Load a filesystem-agent prompt with the data directory resolved."""

    text = load_prompt(name, prompts_dir=prompts_dir)
    return text.replace(SESSION_DATA_DIR_TOKEN, str(Path(session_data_dir)))
