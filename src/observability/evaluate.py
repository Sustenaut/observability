"""The evaluator: each rule run on the facts, its breaches turned into signals.

A signal is one rule's finding about one subject over a span of time. It is
written twice: when it starts (`ended_at` empty) and when it ends, with the
same `started_at`. So a breach that lasts is written once, not every run:
the evaluator is given the signals still open, starts a signal for each
subject newly in breach, and ends each open one no longer in breach (or
whose rule is gone). A rule whose query fails ends nothing: not knowing is
not the same as all clear.

Open signals are the start records without an end, in observability.signals
(OPEN_SIGNALS) and among those written but not loaded yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from observability.config import Dataset
from observability.rules import Rule

# The open signals in BigQuery: start records whose subject and start have no
# end record. A signal open longer than 30 days has been forgotten by this.
OPEN_SIGNALS = """\
SELECT rule_id, rule_version, subject, severity, started_at, TO_JSON_STRING(evidence) AS evidence, emitted_at
FROM observability.signals AS started
WHERE started.ended_at IS NULL
  AND started.started_at >= TIMESTAMP_SUB({{now}}, INTERVAL 30 DAY)
  AND NOT EXISTS (
    SELECT 1 FROM observability.signals AS ended
    WHERE ended.rule_id = started.rule_id AND ended.subject = started.subject
      AND ended.started_at = started.started_at AND ended.ended_at IS NOT NULL
  )
"""


@dataclass(frozen=True)
class Signal:
    rule_id: str
    rule_version: str
    subject: str
    severity: str
    started_at: datetime
    ended_at: datetime | None
    evidence: dict[str, Any]
    emitted_at: datetime

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.subject)

    def record(self) -> dict[str, Any]:
        """As a row of observability.signals, its times in ISO 8601 and evidence as JSON."""
        return {"rule_id": self.rule_id, "rule_version": self.rule_version, "subject": self.subject,
                "severity": self.severity, "started_at": iso(self.started_at),
                "ended_at": iso(self.ended_at) if self.ended_at else None,
                "evidence": json.dumps(self.evidence, sort_keys=True), "emitted_at": iso(self.emitted_at)}


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plain(value: Any) -> Any:
    """A query's value as JSON can hold it."""
    if isinstance(value, datetime):
        return iso(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    return value


def open_signals(rows: list[dict[str, Any]]) -> list[Signal]:
    """Signals from OPEN_SIGNALS's rows."""
    return [Signal(rule_id=r["rule_id"], rule_version=r["rule_version"], subject=r["subject"],
                   severity=r["severity"], started_at=r["started_at"], ended_at=None,
                   evidence=json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r["evidence"] or {},
                   emitted_at=r["emitted_at"]) for r in rows]


@dataclass
class Outcome:
    signals: list[Signal]
    failed: dict[str, str]


def evaluate(rules: list[Rule], query: Callable[[str], list[dict[str, Any]]], datasets: list[Dataset],
             always: list[tuple[str, str]], opened: list[Signal], now: datetime) -> Outcome:
    """The signals to write now: those starting, and those ending."""
    still_open = {signal.key: signal for signal in opened}
    out: list[Signal] = []
    failed: dict[str, str] = {}
    known = {rule.id for rule in rules}
    for rule in rules:
        try:
            rows = query(rule.sql(datasets, always, now))
        except Exception as error:  # noqa: BLE001 - one rule failing doesn't stop the rest
            failed[rule.id] = str(error) or type(error).__name__
            continue
        breaches = {}
        for row in rows:
            evidence = {k: plain(v) for k, v in row.items() if k != "subject" and v is not None}
            breaches[str(row["subject"])] = evidence
        for subject, evidence in sorted(breaches.items()):
            if (rule.id, subject) not in still_open:
                out.append(Signal(rule.id, rule.version, subject, rule.severity, now, None, evidence, now))
        for key, signal in sorted(still_open.items()):
            if key[0] == rule.id and key[1] not in breaches:
                out.append(replace(signal, rule_version=rule.version, ended_at=now, emitted_at=now))
    for key, signal in sorted(still_open.items()):
        if key[0] not in known:
            out.append(replace(signal, ended_at=now, emitted_at=now,
                               evidence={**signal.evidence, "ended_because": "the rule is gone"}))
    return Outcome(out, failed)
