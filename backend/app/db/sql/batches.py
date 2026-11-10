"""Reads a reviewed .sql file from this folder as the batches sqlcmd / SSMS would run (split on GO lines)."""
import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent
_GO = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


def read_batches(name: str) -> list[str]:
    """The non-empty batches of SQL_DIR/name. The files contain no GO inside strings or comments."""
    text = (SQL_DIR / name).read_text(encoding="utf-8")
    return [batch.strip() for batch in _GO.split(text) if _has_code(batch)]


def _has_code(batch: str) -> bool:
    without_comments = re.sub(r"/\*.*?\*/", "", batch, flags=re.DOTALL)
    without_comments = re.sub(r"--[^\n]*", "", without_comments)
    return bool(without_comments.strip())
