"""Runs a fact's BigQuery SQL on fixture rows, locally: sqlglot turns it into
DuckDB's dialect, and DuckDB runs it on tables built from tests/schemas. CI
then needs no BigQuery and no secret."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import sqlglot

HERE = Path(__file__).resolve().parent.parent
DAY = "2026-11-01"
TYPES = {"STRING": "VARCHAR", "INTEGER": "BIGINT", "BOOLEAN": "BOOLEAN", "TIMESTAMP": "TIMESTAMP"}


def schema(table: str) -> list[dict]:
    return json.loads((HERE / "schemas" / f"{table}.json").read_text())


def moment(clock: str) -> datetime:
    """A time of the fixtures' day, such as 10:00:30."""
    return datetime.fromisoformat(f"{DAY}T{clock}")


def complete(table: str, row: dict, n: int) -> dict:
    """A fixture row with the columns it leaves out filled in."""
    row = dict(row)
    row["at"] = moment(row["at"])
    if table == "status":
        row.setdefault("kind", "sender")
        row.setdefault("version", "1")
        row.setdefault("cycle_end", row["at"])
        row.setdefault("cycle_start", row["at"] - timedelta(minutes=2))
    else:
        row.setdefault("repo", "example/repo")
        row.setdefault("request_id", f"r{n}")
        row.setdefault("status", 200 if row.get("outcome", "ok") == "ok" else None)
        row.setdefault("outcome", "ok")
        for column in ("retries", "bytes_in", "bytes_out"):
            row.setdefault(column, 0)
        row.setdefault("mode", "required")
        row.setdefault("route", "routed")
    return row


class Warehouse:
    """The call log datasets, in memory."""

    def __init__(self) -> None:
        self.db = duckdb.connect()
        self.db.execute("SET TimeZone = 'UTC'")
        self.made: set[str] = set()

    def load(self, dataset: str, fixture: str) -> None:
        rows = json.loads((HERE / "fixtures" / f"{fixture}.json").read_text())
        if dataset not in self.made:
            self.db.execute(f"CREATE SCHEMA {dataset}")
            for table in ("status", "calls"):
                columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema(table))
                self.db.execute(f"CREATE TABLE {dataset}.{table} ({columns})")
            self.made.add(dataset)
        for table in ("status", "calls"):
            names = [c["name"] for c in schema(table)]
            for n, row in enumerate(rows.get(table, [])):
                full = complete(table, row, n)
                unknown = set(full) - set(names)
                assert not unknown, f"{fixture}: {table} has no column {', '.join(sorted(unknown))}"
                values = [full.get(name) for name in names]
                self.db.execute(f"INSERT INTO {dataset}.{table} VALUES ({', '.join('?' * len(names))})", values)

    def run(self, bigquery_sql: str) -> list[dict]:
        local = sqlglot.transpile(bigquery_sql, read="bigquery", write="duckdb")[0]
        cursor = self.db.execute(local)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
