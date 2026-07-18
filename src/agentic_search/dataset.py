"""Domain mapping: conference sessions -> Documents / markdown files.

This module is deliberately isolated. When you switch the underlying data
(e.g. to Tour de France data) this is the main file you rewrite: adjust
``load_records``, the field names in ``record_to_document``, and the markdown
layout in ``record_to_markdown``. The search backends, tools, and agent loop
stay the same as long as you keep producing :class:`Document` objects.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import SESSIONS_PATH
from .models import Document


def load_records(path: Path | str = SESSIONS_PATH) -> list[dict]:
    """Load the raw list of session records from the source JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload["sessions"]


def stable_id(record: dict) -> str:
    """A deterministic id for a record, so re-indexing is idempotent."""

    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _speakers_str(record: dict) -> str:
    speakers = record.get("speakers") or []
    if not isinstance(speakers, list):
        speakers = [speakers]
    return ", ".join(str(s) for s in speakers)


def record_to_document(record: dict) -> Document:
    """Turn a session record into a :class:`Document`.

    ``page_content`` is what gets embedded / searched (title + description);
    ``metadata`` holds the structured, filterable fields.
    """

    title = (record.get("title") or "").strip() or "(untitled session)"
    desc = (record.get("description") or "").strip()
    page_content = title if not desc else f"{title}\n\n{desc}"

    return Document(
        page_content=page_content,
        metadata={
            "title": title,
            "description": desc,
            "day": record.get("day") or "",
            "time": record.get("time") or "",
            "room": record.get("room") or "",
            "type": record.get("type") or "",
            "track": record.get("track") or "",
            "speakers": _speakers_str(record),
        },
    )


def display_title(record: dict) -> str:
    """A human-friendly title, falling back to schedule details when missing."""

    title = (record.get("title") or "").strip()
    if title:
        return title
    parts = [record.get("day"), record.get("time"), record.get("room")]
    parts = [p for p in parts if p]
    return " / ".join(parts) if parts else "untitled_session"


def safe_filename(title: str, max_len: int = 120) -> str:
    """Make a title safe to use as a file name."""

    base = re.sub(r'[\\/:*?"<>|]', "", title)
    base = re.sub(r"\s+", " ", base).strip() or "untitled_session"
    if len(base) > max_len:
        base = base[:max_len].rstrip()
    return base


def record_to_markdown(record: dict) -> str:
    """Render a record as a markdown document (used for the filesystem export)."""

    title = display_title(record)
    stype = record.get("type") or "unknown"
    lines = [
        f"# {title}",
        "",
        f"- **Day:** {record.get('day') or '—'}",
        f"- **Time:** {record.get('time') or '—'}",
        f"- **Room:** {record.get('room') or '—'}",
        f"- **Type:** {stype}",
    ]
    if record.get("track"):
        lines.append(f"- **Track:** {record['track']}")
    speakers = _speakers_str(record)
    if speakers:
        lines.append(f"- **Speakers:** {speakers}")
    lines.append("**Description:**")
    desc = (record.get("description") or "").strip()
    if desc:
        lines.append(desc)
    return "\n".join(lines)
