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

A rule may have `params`, its thresholds: each a name (lowercase letters and
underscores) and a number, its default. The query reads one as
`{{param:<name>}}`, which becomes the number:

    params:
      silent_minutes: 10
    query: |
      ... WHERE last_seen < TIMESTAMP_SUB({{now}},
                  INTERVAL CAST({{param:silent_minutes}} * 60 AS INT64) SECOND)

Every param the rule declares is used, and every one it uses is declared.
OBSERVABILITY_THRESHOLDS can set another number for any of them, and another
severity (observability.thresholds); a rule then runs with those, its
effective params, and each signal it starts records them in its evidence, as
`thresholds`.

A rule may also have a `trend`, which the signal's page charts (it never
changes what the rule finds, so it needs no new version):

    trend:
      label: Slowest warm answer, ms   # what the value is
      threshold: 5000                  # where the rule says breach: a number, or a param's name
      query: |                         # one row per subject and bucket
        SELECT ... AS subject, bucket, ... AS value

It reads facts, params and placeholders as the query does, over the window
the page shows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib import resources

from observability import facts
from observability.config import Dataset

SEVERITIES = ("critical", "warning", "info")
KEYS = {"id", "version", "severity", "summary", "lookback_minutes", "query"}
OPTIONAL = {"trend", "params"}
TREND_KEYS = {"label", "threshold", "query"}
FACT = re.compile(r"\{\{fact:([a-z_]+)\}\}")
PARAM = re.compile(r"\{\{param:([a-z_]+)\}\}")
PARAM_NAME = re.compile(r"[a-z_]+")
# Anything in double braces: each must be a fact, a param or a known placeholder.
BRACED = re.compile(r"\{\{(.*?)\}\}")
KNOWN = {"now", "projects", "always_senders"}


@dataclass(frozen=True)
class Trend:
    label: str
    threshold: float | str  # a number, or the name of one of the rule's params
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
    # Its params, by name: the file's defaults, or the effective ones once
    # OBSERVABILITY_THRESHOLDS is applied (observability.thresholds).
    params: dict[str, float] = field(default_factory=dict)

    def sql(self, datasets: list[Dataset], always: list[tuple[str, str]], now: datetime) -> str:
        """The query for these datasets and senders, at `now`, with the rule's params."""
        return render(self.query, self.lookback_minutes, datasets, always, now, self.params)

    def trend_sql(self, datasets: list[Dataset], minutes: int, now: datetime) -> str:
        """The trend's query, over `minutes` up to `now`, with the rule's params."""
        assert self.trend is not None
        return render(self.trend.query, minutes, datasets, [], now, self.params)

    @property
    def threshold(self) -> float:
        """Where its trend says breach, with the rule's params."""
        assert self.trend is not None
        found = self.trend.threshold
        return float(self.params[found] if isinstance(found, str) else found)


def number(value: float) -> str:
    """A param's number as SQL reads it."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def render(query: str, lookback_minutes: int, datasets: list[Dataset], always: list[tuple[str, str]],
           now: datetime, params: dict[str, float] | None = None) -> str:
    """A query over the facts, its placeholders filled in: the rules', and any other
    reader's, such as the trends page. `params` are the effective params its
    `{{param:<name>}}` read."""
    known = facts.load()
    since = now - timedelta(minutes=lookback_minutes)
    given = params or {}
    text = PARAM.sub(lambda m: number(given[m.group(1)]), query)
    text = FACT.sub(lambda m: f"(\n{known[m.group(1)].union(datasets, since)}\n)", text)
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
    declared = params(name, data.get("params"))
    query = checked(name, str(data["query"]), declared)
    found = trend(name, data.get("trend"), declared)
    used = set(PARAM.findall(query))
    if found is not None:
        used |= set(PARAM.findall(found.query)) | ({found.threshold} if isinstance(found.threshold, str) else set())
    unused = sorted(set(declared) - used)
    if unused:
        raise ValueError(f"{name}.yaml: no query uses the param {', '.join(unused)}")
    return Rule(id=name, version=str(data["version"]), severity=data["severity"], summary=str(data["summary"]),
                lookback_minutes=data["lookback_minutes"], query=query, trend=found, params=declared)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def params(name: str, data: object) -> dict[str, float]:
    """A rule's params, each a name and a number."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{name}.yaml: params maps each name to a number")
    for key, value in data.items():
        if not isinstance(key, str) or not PARAM_NAME.fullmatch(key):
            raise ValueError(f"{name}.yaml: a param's name is lowercase letters and underscores, not {key}")
        if not is_number(value):
            raise ValueError(f"{name}.yaml: the param {key} is a number, not {value}")
    return dict(data)


def checked(name: str, query: str, declared: dict[str, float]) -> str:
    """`query`, once every fact, param and placeholder in it is known."""
    for inside in BRACED.findall(query):
        kind, _, what = inside.partition(":")
        if kind == "fact" and FACT.fullmatch(f"{{{{{inside}}}}}"):
            if what not in facts.load():
                raise ValueError(f"{name}.yaml: there is no fact {what}")
        elif kind == "param" and PARAM.fullmatch(f"{{{{{inside}}}}}"):
            if what not in declared:
                raise ValueError(f"{name}.yaml: {{{{param:{what}}}}} is not among its params")
        elif inside not in KNOWN:
            raise ValueError(f"{name}.yaml: there is no {{{{{inside}}}}}")
    return query


def trend(name: str, data: object, declared: dict[str, float]) -> Trend | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != TREND_KEYS:
        raise ValueError(f"{name}.yaml: a trend has {', '.join(sorted(TREND_KEYS))}, and nothing else")
    threshold = data["threshold"]
    if isinstance(threshold, str):
        if threshold not in declared:
            raise ValueError(f"{name}.yaml: a trend's threshold {threshold} is not among its params")
    elif not is_number(threshold):
        raise ValueError(f"{name}.yaml: a trend's threshold is a number, or one of its params")
    return Trend(label=str(data["label"]), threshold=threshold if isinstance(threshold, str) else float(threshold),
                 query=checked(name, str(data["query"]), declared))


def load() -> dict[str, Rule]:
    """Every rule in this package, by id."""
    import yaml  # noqa: PLC0415 - only the rules need it

    files = sorted(f for f in resources.files(__name__).iterdir() if f.name.endswith(".yaml"))
    return {rule.id: rule for rule in (parse(f.name.removesuffix(".yaml"), yaml.safe_load(f.read_text()))
                                       for f in files)}
