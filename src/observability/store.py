"""Signals in storage's `signals` tenant, waiting for the integrations ingest pod
to load them into observability.signals and delete them.

Each run writes one Avro file of its signals to `inbox/signals/<date>/`. The
same signals always give the same bytes, and the file is named for its
content, so writing one again replaces it. What is in the inbox is what the
ingest pod hasn't loaded yet, so the evaluator reads it back, with
observability.signals, to know which signals are open (`still_open`).
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone

import fastavro

from observability.evaluate import Signal

INBOX = "inbox/signals/"
_TIME = {"type": "long", "logicalType": "timestamp-micros"}
# The columns of observability.signals; evidence is JSON, which BigQuery reads
# from a string marked sqlType JSON.
SCHEMA = fastavro.parse_schema({
    "type": "record", "name": "signal", "fields": [
        {"name": "rule_id", "type": "string"},
        {"name": "rule_version", "type": "string"},
        {"name": "subject", "type": "string"},
        {"name": "severity", "type": "string"},
        {"name": "started_at", "type": _TIME},
        {"name": "ended_at", "type": ["null", _TIME], "default": None},
        {"name": "evidence", "type": {"type": "string", "sqlType": "JSON"}},
        {"name": "emitted_at", "type": _TIME},
    ]})


def _row(signal: Signal) -> dict:
    return {"rule_id": signal.rule_id, "rule_version": signal.rule_version, "subject": signal.subject,
            "severity": signal.severity, "started_at": signal.started_at, "ended_at": signal.ended_at,
            "evidence": json.dumps(signal.evidence, sort_keys=True), "emitted_at": signal.emitted_at}


def encode(signals: list[Signal]) -> bytes:
    rows = [_row(s) for s in signals]
    marker = hashlib.sha256(repr([sorted(r.items()) for r in rows]).encode()).digest()[:16]
    out = io.BytesIO()
    fastavro.writer(out, SCHEMA, rows, codec="deflate", sync_marker=marker,
                    metadata={"observability.schema": "signal"})
    return out.getvalue()


def decode(data: bytes) -> list[Signal]:
    def utc(moment: datetime | None) -> datetime | None:
        return moment.astimezone(timezone.utc) if moment else None

    return [Signal(rule_id=r["rule_id"], rule_version=r["rule_version"], subject=r["subject"],
                   severity=r["severity"], started_at=utc(r["started_at"]), ended_at=utc(r["ended_at"]),
                   evidence=json.loads(r["evidence"]), emitted_at=utc(r["emitted_at"]))
            for r in fastavro.reader(io.BytesIO(data))]


def place(now: datetime, data: bytes) -> str:
    """Where a run's file goes: named for when, who, and what is in it."""
    moment = now.astimezone(timezone.utc)
    return f"{INBOX}{moment:%Y-%m-%d}/{moment:%H%M%S}-evaluator-{hashlib.sha256(data).hexdigest()[:16]}.avro"


def still_open(loaded: list[Signal], pending: list[Signal]) -> list[Signal]:
    """The open signals: those open in observability.signals, with the starts and
    ends written since and not loaded yet laid over them in the order they were
    written."""
    opened = {signal.key: signal for signal in loaded}
    for signal in sorted(pending, key=lambda s: (s.emitted_at, s.ended_at is not None)):
        if signal.ended_at is None:
            opened[signal.key] = signal
        elif signal.key in opened and opened[signal.key].started_at == signal.started_at:
            del opened[signal.key]
    return list(opened.values())


class Store:
    """The signals tenant, through the integrations library's storage client."""

    def __init__(self, storage):  # integrations.clients.storage.Storage
        self.storage = storage

    def pending(self) -> list[Signal]:
        """The signals written and not loaded yet. A file gone between its listing
        and its reading has just been loaded, and is in observability.signals."""
        from integrations.clients.storage import NotFound  # noqa: PLC0415

        found: list[Signal] = []
        for entry in self.storage.list_buffer(INBOX):
            try:
                found += decode(self.storage.get_buffer(entry["name"]))
            except NotFound:
                continue
        return found

    def write(self, signals: list[Signal], now: datetime) -> str | None:
        """The place they were written, or None when there was nothing to write."""
        if not signals:
            return None
        data = encode(signals)
        where = place(now, data)
        self.storage.put_buffer(where, data)
        return where
