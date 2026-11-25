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
        # The convergence engine's table is always there, as Terraform makes it, if empty.
        self.need_states([])
        # And the platform's pubrules checks, likewise.
        self.pubrules_checks([])
        # And the uptime probe's rows.
        self.uptime_probes([])
        self.incidents([])

    def load(self, dataset: str, fixture: str) -> None:
        self.hold(dataset, json.loads((HERE / "fixtures" / f"{fixture}.json").read_text()), fixture)

    def hold(self, dataset: str, rows: dict, fixture: str = "the rows") -> None:
        """The dataset, holding these rows of its tables as a fixture writes them."""
        if dataset not in self.made:
            self.db.execute(f"CREATE SCHEMA {dataset}")
            for table in ("status", "calls"):
                columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema(table))
                self.db.execute(f"CREATE TABLE {dataset}.{table} ({columns})")
            self.made.add(dataset)
        for table in ("status", "calls"):
            names = [c["name"] for c in schema(table)]
            expanded = [dict(r) for r in rows.get(table, []) for _ in range(r.pop("repeat", 1) if "repeat" in r else 1)]
            for n, row in enumerate(expanded):
                full = complete(table, row, n)
                unknown = set(full) - set(names)
                assert not unknown, f"{fixture}: {table} has no column {', '.join(sorted(unknown))}"
                values = [full.get(name) for name in names]
                self.db.execute(f"INSERT INTO {dataset}.{table} VALUES ({', '.join('?' * len(names))})", values)

    def _observability(self) -> None:
        if "observability" not in self.made:
            self.db.execute("CREATE SCHEMA observability")
            self.made.add("observability")

    def signals(self, rows: list[dict]) -> None:
        """observability.signals, holding these rows."""
        self._observability()
        if "observability.signals" not in self.made:
            self.db.execute("CREATE TABLE observability.signals (rule_id VARCHAR, rule_version VARCHAR, subject VARCHAR,"
                            " severity VARCHAR, started_at TIMESTAMP, ended_at TIMESTAMP, evidence JSON,"
                            " emitted_at TIMESTAMP)")
            self.made.add("observability.signals")
        for row in rows:
            self.db.execute("INSERT INTO observability.signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            [row["rule_id"], row.get("rule_version", "1"), row["subject"], row.get("severity", "warning"),
                             moment(row["started_at"]), moment(row["ended_at"]) if row.get("ended_at") else None,
                             json.dumps(row.get("evidence", {})), moment(row["started_at"])])

    def need_states(self, rows: list[dict]) -> None:
        """convergence.need_states, holding these rows: a walk's time as the fixtures' clock."""
        if "convergence" not in self.made:
            self.db.execute("CREATE SCHEMA convergence")
            columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema("need_states"))
            self.db.execute(f"CREATE TABLE convergence.need_states ({columns})")
            self.made.add("convergence")
        names = [c["name"] for c in schema("need_states")]
        for row in rows:
            at = moment(row["walk"])
            full = {"observed_at": at, "unit": row["repository"].split("/")[1], "type": row["need"].split(":")[0],
                    "name": row["need"].split(":", 1)[1], "grade": "auto", "walked_from": "plane",
                    "walk_started_at": at, **{k: v for k, v in row.items() if k != "walk"}}
            self.db.execute(f"INSERT INTO convergence.need_states VALUES ({', '.join('?' * len(names))})",
                            [full[n] for n in names])

    def pubrules_checks(self, rows: list[dict]) -> None:
        """platform.pubrules_checks, holding these rows: a night's check time as the fixtures' clock."""
        if "platform" not in self.made:
            self.db.execute("CREATE SCHEMA platform")
            columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema("pubrules_checks"))
            self.db.execute(f"CREATE TABLE platform.pubrules_checks ({columns})")
            self.made.add("platform")
        names = [c["name"] for c in schema("pubrules_checks")]
        for row in rows:
            at = moment(row["night"])
            full = {"observed_at": at, "pinned": "", "latest": "", "main_commit": "", "run_url": "", "fix": "",
                    "run_started_at": at, **{k: v for k, v in row.items() if k != "night"}}
            self.db.execute(f"INSERT INTO platform.pubrules_checks VALUES ({', '.join('?' * len(names))})",
                            [full[n] for n in names])

    def incidents(self, rows: list[dict]) -> None:
        """observability.incidents_view, holding these rows: their times as the fixtures' clock."""
        self._observability()
        if "observability.incidents_view" not in self.made:
            columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema("incidents_view"))
            self.db.execute(f"CREATE TABLE observability.incidents_view ({columns})")
            self.made.add("observability.incidents_view")
        names = [c["name"] for c in schema("incidents_view")]
        for row in rows:
            full = {"policy_name": f"projects/p/alertPolicies/{row['incident']}", "summary": "s", "severity": "CRITICAL",
                    "condition_name": "c", "url": f"https://console.example/{row['incident']}", "tier": "tight",
                    "started_at": moment(row["started"]), "ended_at": None, "incident_id": row["incident"],
                    "publish_time": moment(row["at"]),
                    **{k: v for k, v in row.items() if k not in ("at", "started", "incident") and v != ""}}
            self.db.execute(f"INSERT INTO observability.incidents_view VALUES ({', '.join('?' * len(names))})",
                            [full[n] for n in names])

    def uptime_probes(self, rows: list[dict]) -> None:
        """observability.uptime_probes, holding these rows: a probe's time as the fixtures' clock."""
        self._observability()
        if "observability.uptime_probes" not in self.made:
            columns = ", ".join(f'"{c["name"]}" {TYPES[c["type"]]}' for c in schema("uptime_probes"))
            self.db.execute(f"CREATE TABLE observability.uptime_probes ({columns})")
            self.made.add("observability.uptime_probes")
        names = [c["name"] for c in schema("uptime_probes")]
        for n, row in enumerate(rows):
            up = row["up"] == "true"
            full = {"probed_at": moment(row["at"]), "execution": f"run-{n}", "url": f"https://{row['target']}.test/healthz",
                    "status": 200 if up else 503, "expect_status": 200, "detail": "HTTP 200" if up else "HTTP 503, not 200",
                    "attempts": 1 if up else 2, "elapsed_ms": 40, **{k: v for k, v in row.items() if k not in ("at", "up")},
                    "up": up}
            self.db.execute(f"INSERT INTO observability.uptime_probes VALUES ({', '.join('?' * len(names))})",
                            [full[n] for n in names])

    def typed(self, bigquery_sql: str) -> tuple[list[tuple[str, str]], list[tuple]]:
        """Each column's name and DuckDB type, and the rows."""
        local = sqlglot.transpile(bigquery_sql, read="bigquery", write="duckdb")[0]
        cursor = self.db.execute(local)
        return [(d[0], str(d[1])) for d in cursor.description], cursor.fetchall()

    def run(self, bigquery_sql: str) -> list[dict]:
        columns, rows = self.typed(bigquery_sql)
        return [dict(zip([c[0] for c in columns], row)) for row in rows]
