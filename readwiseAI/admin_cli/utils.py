"""Utility functions for the admin CLI."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def print_table(headers: list, rows: list) -> None:
    """Print a simple text table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    sep = "  "
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider = sep.join("-" * w for w in col_widths)
    print(header_line)
    print(divider)
    for row in rows:
        print(sep.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))


def confirm(prompt: str) -> bool:
    """Ask for confirmation, return True if confirmed."""
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
