"""Rows as the feature files' tables write them, for pubtest's `the result is:`:
a time as HH:MM, a boolean as true or false, nothing as an empty cell."""

from __future__ import annotations

from datetime import datetime


def shown(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    return str(value)


def table(rows: list[dict], *, ordered: bool = False) -> list[dict]:
    """Every row with each value shown; in a stable order, its cells in turn,
    unless the rows' own order is what is checked."""
    out = [{key: shown(value) for key, value in row.items()} for row in rows]
    return out if ordered else sorted(out, key=lambda row: list(row.values()))
