"""Rules: what in the facts is worth a signal, as versioned YAML.

Each rule is one `.yaml` file here:

    id: sender_silent           # its file's name
    version: 1                  # up whenever what it finds could change
    severity: critical          # critical, warning or info
    summary: One sentence on what it finds.
    lookback_minutes: 60        # how far back the facts it reads go
    query: |                    # BigQuery standard SQL over the facts
      SELECT ... AS subject, ...

A query returns one row per subject in breach now; `subject` names it, and
every other column is the signal's evidence. It reads facts as
`{{fact:<id>}}`, every configured dataset's rows together from its
lookback on, and may use `{{now}}`, the moment evaluated, `{{projects}}`,
a table of the configured projects (`project`), and `{{always_senders}}`,
a table of the senders expected to report all the time (`project`,
`sender_prefix`).

A rule may also have a `trend`, which the signal's page charts (it never
changes what the rule finds, so it needs no new version):

    trend:
      label: Slowest warm answer, ms   # what the value is
      threshold: 5000                  # where the rule says breach
      query: |                         # one row per subject and bucket
        SELECT ... AS subject, bucket, ... AS value

It reads facts and placeholders as the query does, over the window the page
shows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import resources

from observability import facts
from observability.config import Dataset

SEVERITIES = ("critical", "warning", "info")
KEYS = {"id", "version", "severity", "summary", "lookback_minutes", "query"}
OPTIONAL = {"trend"}
TREND_KEYS = {"label", "threshold", "query"}
FACT = re.compile(r"\{\{fact:([a-z_]+)\}\}")
PLACEHOLDER = re.compile(r"\{\{(?!fact:)([a-z_]+)\}\}")
KNOWN = {"now", "projects", "always_senders"}


@dataclass(frozen=True)
class Trend:
    label: str
    threshold: float
    query: str


@dataclass(frozen=True)
class Rule:
    id: str
    version: str
    severity: str
    summary: str
    lookback_minutes: int
    query: str
    trend: Trend | None = None

    def sql(self, datasets: list[Dataset], always: list[tuple[str, str]], now: datetime) -> str:
        """The query for these datasets and senders, at `now`."""
        return render(self.query, self.lookback_minutes, datasets, always, now)


def render(query: str, lookback_minutes: int, datasets: list[Dataset], always: list[tuple[str, str]],
           now: datetime) -> str:
    """A query over the facts, its placeholders filled in: the rules', and any other
    reader's, such as the trends page."""
    known = facts.load()
    since = now - timedelta(minutes=lookback_minutes)
    text = FACT.sub(lambda m: f"(\n{known[m.group(1)].union(datasets, since)}\n)", query)
    projects = [(d.project,) for d in datasets]
    return (text.replace("{{now}}", facts.timestamp(now))
            .replace("{{projects}}", table(("project",), projects))
            .replace("{{always_senders}}", table(("project", "sender_prefix"), always)))


def literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def table(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """A table of strings, as a subquery; with no rows, one that is empty."""
    if not rows:
        nulls = ", ".join(f"CAST(NULL AS STRING) AS {c}" for c in columns)
        return f"(SELECT {nulls} FROM UNNEST([1]) WHERE FALSE)"
    selects = [", ".join(f"{literal(v)} AS {c}" for v, c in zip(row, columns)) for row in rows]
    return "(" + " UNION ALL ".join(f"SELECT {s}" for s in selects) + ")"


def parse(name: str, data: object) -> Rule:
    """A rule from its file's YAML, each field checked."""
    if not isinstance(data, dict):
        raise ValueError(f"{name}.yaml: a rule is a mapping")
    missing, unknown = sorted(KEYS - set(data)), sorted(set(data) - KEYS - OPTIONAL)
    if missing or unknown:
        what = "; ".join(filter(None, [missing and f"no {', '.join(missing)}",
                                       unknown and f"no setting {', '.join(unknown)}"]))
        raise ValueError(f"{name}.yaml: {what}")
    if data["id"] != name:
        raise ValueError(f"{name}.yaml: its id is {data['id']}")
    if data["severity"] not in SEVERITIES:
        raise ValueError(f"{name}.yaml: severity is {', '.join(SEVERITIES)}, not {data['severity']}")
    if not isinstance(data["lookback_minutes"], int) or data["lookback_minutes"] < 2:
        raise ValueError(f"{name}.yaml: lookback_minutes is a whole number of minutes, at least 2")
    query = checked(name, str(data["query"]))
    return Rule(id=name, version=str(data["version"]), severity=data["severity"], summary=str(data["summary"]),
                lookback_minutes=data["lookback_minutes"], query=query, trend=trend(name, data.get("trend")))


def checked(name: str, query: str) -> str:
    """`query`, once every fact and placeholder in it is known."""
    for fact in FACT.findall(query):
        if fact not in facts.load():
            raise ValueError(f"{name}.yaml: there is no fact {fact}")
    for placeholder in PLACEHOLDER.findall(query):
        if placeholder not in KNOWN:
            raise ValueError(f"{name}.yaml: there is no {{{{{placeholder}}}}}")
    return query


def trend(name: str, data: object) -> Trend | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != TREND_KEYS:
        raise ValueError(f"{name}.yaml: a trend has {', '.join(sorted(TREND_KEYS))}, and nothing else")
    if isinstance(data["threshold"], bool) or not isinstance(data["threshold"], (int, float)):
        raise ValueError(f"{name}.yaml: a trend's threshold is a number")
    return Trend(label=str(data["label"]), threshold=float(data["threshold"]),
                 query=checked(name, str(data["query"])))


def load() -> dict[str, Rule]:
    """Every rule in this package, by id."""
    import yaml  # noqa: PLC0415 - only the rules need it

    files = sorted(f for f in resources.files(__name__).iterdir() if f.name.endswith(".yaml"))
    return {rule.id: rule for rule in (parse(f.name.removesuffix(".yaml"), yaml.safe_load(f.read_text()))
                                       for f in files)}
