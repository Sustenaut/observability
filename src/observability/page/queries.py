"""What the trends page asks BigQuery: the facts over the last day, and the signals.

Each query is BigQuery standard SQL over the facts, rendered as a rule's is
(rules.render), so the page reads the very rows the rules judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from observability import facts, rules
from observability.config import Dataset
from observability.evaluate import OPEN_SIGNALS

DAY_MINUTES = 24 * 60
# A sender is silent after this long without a report: sender_silent's threshold.
SILENT = timedelta(minutes=6)
# The newest answering windows shown for each sender.
WINDOWS = 30

PLUGINS = """\
SELECT
  project, app, plugin, operation,
  SUM(calls) AS call_count,
  SUM(errors) AS error_count,
  SUM(refused) AS refused_count,
  SUM(unavailable) AS unavailable_count,
  CAST(ROUND(SAFE_DIVIDE(SUM(latency_ms_median * calls), SUM(calls))) AS INT64) AS typical_ms,
  MAX(latency_ms_max) AS slowest_ms
FROM {{fact:call_rollups}}
WHERE scope = 'plugin'
GROUP BY project, app, plugin, operation
"""

SENDERS = """\
SELECT
  project, kind, sender_prefix,
  MAX(last_cycle_end) AS last_seen,
  COUNTIF(bucket >= TIMESTAMP_SUB({{now}}, INTERVAL 1 HOUR)) AS windows_last_hour
FROM {{fact:sender_windows}}
GROUP BY project, kind, sender_prefix
"""

PAGE_TIMES = """\
SELECT
  project, sender_prefix, bucket, page_count, page_ms_low, page_ms_median, page_ms_high,
  page_ms_median_approximate, cold_start
FROM {{fact:sender_windows}}
WHERE kind = 'sender' AND page_count > 0
"""

RECENT_SIGNALS = """\
SELECT rule_id, subject, severity, started_at, ended_at
FROM observability.signals
WHERE ended_at IS NOT NULL AND ended_at >= TIMESTAMP_SUB({{now}}, INTERVAL 1 DAY)
ORDER BY ended_at DESC
LIMIT 50
"""


@dataclass(frozen=True)
class Sender:
    project: str
    kind: str
    prefix: str
    expected: str  # always, on-demand, or "" when the configuration doesn't name it
    last_seen: datetime | None
    windows_last_hour: int
    silent: bool


@dataclass
class Trends:
    now: datetime
    plugins: list[dict[str, Any]] = field(default_factory=list)
    senders: list[Sender] = field(default_factory=list)
    page_times: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    open_signals: list[dict[str, Any]] = field(default_factory=list)
    recent_signals: list[dict[str, Any]] = field(default_factory=list)


def utc(moment: datetime) -> datetime:
    """A query's time, in UTC: BigQuery's carry their zone, and one that doesn't is UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def senders(rows: list[dict[str, Any]], expected: dict[str, dict[str, str]], now: datetime) -> list[Sender]:
    """Every sender seen in the last day, and every one configured though not seen."""
    found: dict[tuple[str, str, str], Sender] = {}
    for row in rows:
        kind = expected.get(row["project"], {}).get(row["sender_prefix"], "") if row["kind"] == "sender" else ""
        last_seen = utc(row["last_seen"])
        silent = kind == "always" and now - last_seen > SILENT
        found[(row["project"], row["kind"], row["sender_prefix"])] = Sender(
            row["project"], row["kind"], row["sender_prefix"], kind, last_seen,
            int(row["windows_last_hour"]), silent)
    for project, prefixes in expected.items():
        for prefix, kind in prefixes.items():
            if (project, "sender", prefix) not in found:
                found[(project, "sender", prefix)] = Sender(project, "sender", prefix, kind, None, 0, kind == "always")
    return [found[key] for key in sorted(found)]


def trends(query: Callable[[str], list[dict[str, Any]]], datasets: list[Dataset],
           expected: dict[str, dict[str, str]], now: datetime) -> Trends:
    """Everything the page shows, at `now`."""
    def run(text: str) -> list[dict[str, Any]]:
        return query(rules.render(text, DAY_MINUTES, datasets, [], now))

    out = Trends(now)
    out.plugins = sorted(run(PLUGINS), key=lambda r: (r["project"], r["app"], r["plugin"], r["operation"]))
    out.senders = senders(run(SENDERS), expected, now)
    for row in sorted(run(PAGE_TIMES), key=lambda r: r["bucket"], reverse=True):
        windows = out.page_times.setdefault((row["project"], row["sender_prefix"]), [])
        if len(windows) < WINDOWS:
            windows.append(row)
    stamp = facts.timestamp(now)
    out.open_signals = sorted(query(OPEN_SIGNALS.replace("{{now}}", stamp)),
                              key=lambda r: (r["severity"] != "critical", r["started_at"]))
    out.recent_signals = query(RECENT_SIGNALS.replace("{{now}}", stamp))
    return out


# A signal's page: the hour before it began, and half an hour after it ended.
BEFORE = timedelta(hours=1)
AFTER = timedelta(minutes=30)
# Its rule's other signals for the same subject, newest first.
HISTORY = 20

# The signal: its rule and the second it began, which a rule id and a timestamp
# can name safely; its subject, which could hold anything, is matched here.
SIGNAL = """\
SELECT rule_id, rule_version, subject, severity, started_at, ended_at, TO_JSON_STRING(evidence) AS evidence,
  emitted_at
FROM observability.signals
WHERE rule_id = {{rule}} AND started_at >= {{from}} AND started_at < {{to}}
"""

SIGNAL_HISTORY = """\
SELECT rule_id, subject, severity, started_at, ended_at
FROM observability.signals
WHERE rule_id = {{rule}} AND started_at >= TIMESTAMP_SUB({{now}}, INTERVAL 30 DAY)
"""

# What the signal's evidence is about, around it: a sender's or the ingest pod's
# windows, or an app's calls to a plugin.
SENDER_WINDOWS = """\
SELECT project, kind, sender_prefix, bucket, reports, calls, drops, storage_failures, page_count,
  page_ms_median, page_ms_high, cold_start, waiting_files, waiting_oldest_seconds, rejected_files, problems
FROM {{fact:sender_windows}}
"""

PLUGIN_CALLS = """\
SELECT project, app, plugin, operation, bucket, calls, errors, refused, unavailable, latency_ms_median,
  latency_ms_max
FROM {{fact:call_rollups}}
WHERE scope = 'plugin'
"""


@dataclass
class SignalView:
    now: datetime
    rule: rules.Rule
    signal: dict[str, Any]
    since: datetime
    until: datetime
    evidence: dict[str, Any] = field(default_factory=dict)
    trend: list[dict[str, Any]] = field(default_factory=list)
    context: str = ""  # "sender", "ingest", "plugin" or "" for none
    rows: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


def _merged(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each signal once: a signal is written when it starts and again when it ends."""
    found: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row["subject"], utc(row["started_at"]))
        if key not in found or row.get("ended_at") is not None:
            found[key] = row
    return list(found.values())


def _context(evidence: dict[str, Any]) -> str:
    if "plugin" in evidence and "app" in evidence:
        return "plugin"
    if "sender_prefix" in evidence:
        return "sender"
    return "ingest" if "project" in evidence else ""


def signal(query: Callable[[str], list[dict[str, Any]]], datasets: list[Dataset], every: dict[str, rules.Rule],
           rule_id: str, subject: str, started_at: datetime, now: datetime) -> SignalView | None:
    """Everything a signal's page shows, or None when there is no such signal."""
    import json  # noqa: PLC0415

    rule = every.get(rule_id)
    if rule is None:
        return None
    second = started_at.replace(microsecond=0)
    found = _merged([r for r in query(SIGNAL.replace("{{rule}}", rules.literal(rule_id))
                                      .replace("{{from}}", facts.timestamp(second))
                                      .replace("{{to}}", facts.timestamp(second + timedelta(seconds=1))))
                     if r["subject"] == subject and utc(r["started_at"]) == started_at])
    if not found:
        return None
    row = found[0]
    ended = utc(row["ended_at"]) if row.get("ended_at") is not None else None
    since, until = started_at - BEFORE, min(now, (ended or now) + AFTER)
    minutes = max(2, int((until - since).total_seconds() // 60) + 2)
    evidence = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else dict(row["evidence"] or {})
    out = SignalView(now, rule, row, since, until, evidence)

    def run(text: str) -> list[dict[str, Any]]:
        return query(rules.render(text, minutes, datasets, [], until))

    def within(r: dict[str, Any]) -> bool:
        return since <= utc(r["bucket"]) <= until

    if rule.trend is not None:
        out.trend = sorted((r for r in run(rule.trend.query) if r["subject"] == subject and within(r)),
                           key=lambda r: r["bucket"])
    out.context = _context(evidence)
    project = evidence.get("project", subject.split("/")[0])
    if out.context == "plugin":
        rows = [r for r in run(PLUGIN_CALLS) if (r["project"], r["app"], r["plugin"])
                == (project, evidence["app"], evidence["plugin"])]
    elif out.context == "sender":
        rows = [r for r in run(SENDER_WINDOWS) if (r["project"], r["kind"], r["sender_prefix"])
                == (project, "sender", evidence["sender_prefix"])]
    elif out.context == "ingest":
        rows = [r for r in run(SENDER_WINDOWS) if (r["project"], r["kind"]) == (project, "ingest")]
    else:
        rows = []
    out.rows = sorted((r for r in rows if within(r)), key=lambda r: r["bucket"], reverse=True)
    stamp = facts.timestamp(now)
    history = query(SIGNAL_HISTORY.replace("{{rule}}", rules.literal(rule_id)).replace("{{now}}", stamp))
    out.history = sorted((r for r in _merged(history) if r["subject"] == subject),
                         key=lambda r: utc(r["started_at"]), reverse=True)[:HISTORY]
    return out
