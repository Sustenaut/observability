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
