"""Facts: what the call log says, as versioned BigQuery queries.

Each fact is one `.sql` file here, in BigQuery standard SQL, whose header
names it and gives its version:

    -- fact: sender_windows
    -- version: 1
    -- reads: status

The version goes up whenever a change could change a row, and every row
carries `fact` and `fact_version`, so a signal derived from a fact can be
traced to the query that produced it. A query reads one project's dataset,
written `{{dataset}}`, and names that project `{{project}}`; neither is
in this repository, since which datasets exist is configuration. It reads
rows from `{{since}}` on, a bucket's start: a rule's lookback, or all of
them when none is given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import resources

from observability.config import Dataset

HEADER = re.compile(r"^-- (fact|version|reads): (\S+)$", re.MULTILINE)
BUCKET = timedelta(minutes=2)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def timestamp(moment: datetime) -> str:
    """A BigQuery TIMESTAMP literal, in UTC."""
    return f"TIMESTAMP '{moment.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}+00:00'"


def bucket_start(moment: datetime) -> datetime:
    """The start of the two-minute bucket a moment is in."""
    return EPOCH + (moment - EPOCH) // BUCKET * BUCKET


@dataclass(frozen=True)
class Fact:
    """One fact's query, as written."""

    id: str
    version: str
    reads: str
    template: str

    def sql(self, dataset: Dataset, since: datetime | None = None) -> str:
        """The query for one project's dataset, from the bucket `since` is in."""
        start = timestamp(bucket_start(since) if since else EPOCH)
        return (self.template.replace("{{dataset}}", dataset.name).replace("{{project}}", dataset.project)
                .replace("{{since}}", start))

    def union(self, datasets: list[Dataset], since: datetime | None = None) -> str:
        """The query for several projects at once, their rows together."""
        return "\nUNION ALL\n".join(f"(\n{self.sql(dataset, since)})" for dataset in datasets)


def parse(name: str, text: str) -> Fact:
    """A fact from its file's text; its header must name it as its file does."""
    header = dict(HEADER.findall(text))
    missing = sorted({"fact", "version", "reads"} - set(header))
    if missing:
        raise ValueError(f"{name}.sql: its header has no {', '.join(missing)}")
    if header["fact"] != name:
        raise ValueError(f"{name}.sql: its header names it {header['fact']}")
    return Fact(id=name, version=header["version"], reads=header["reads"], template=text)


def load() -> dict[str, Fact]:
    """Every fact in this package, by id."""
    files = sorted(f for f in resources.files(__name__).iterdir() if f.name.endswith(".sql"))
    return {fact.id: fact for fact in (parse(f.name.removesuffix(".sql"), f.read_text()) for f in files)}
