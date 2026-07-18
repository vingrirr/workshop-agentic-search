"""Filesystem export for the shell-tool technique (notebook 03).

Writes one markdown file per record, grouped into subfolders by ``type``::

    data/session_data/
      workshop/
        Some Title.txt
      talk/
        ...

The shell agent then searches these files with ``grep`` / ``find`` / ``cat``
(and optionally ``jina-grep`` for semantic search). This is independent of the
search backend - it works straight from the source records.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..config import SESSION_DATA_DIR
from ..dataset import display_title, record_to_markdown, safe_filename


def export_records_by_type(
    records: list[dict], root: Path | str = SESSION_DATA_DIR
) -> Path:
    """(Re)create ``root`` and write one ``.txt`` file per record."""

    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    counts: dict[tuple[str, str], int] = {}
    for record in records:
        rtype = (record.get("type") or "unknown").strip() or "unknown"
        type_dir = root / rtype
        type_dir.mkdir(parents=True, exist_ok=True)

        base = safe_filename(display_title(record))
        key = (rtype, base)
        n = counts.get(key, 0)
        counts[key] = n + 1
        name = base if n == 0 else f"{base}__{n + 1}"

        (type_dir / f"{name}.txt").write_text(
            record_to_markdown(record), encoding="utf-8"
        )

    return root
