"""BigQuery queries, through the integrations library's Caller, so each call has
its class's timeout and retries and is declared as google.bigquery's query.

    warehouse = Warehouse(caller, key)       # key: a service account's key, as a dict
    rows = warehouse.query("SELECT 1 AS one")  # [{"one": 1}]
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode

from integrations.calls import Caller, Refused, Request
from integrations.ingest.google_token import GoogleToken

PLUGIN = "google.bigquery"
API = "https://bigquery.googleapis.com/bigquery/v2"
# How long BigQuery may hold a request open for a query to finish.
WAIT_MS = 10_000
# How many times to ask again for a query still running.
POLLS = 6


def value(field: dict, raw: Any) -> Any:
    """One cell of a query's answer, by its field's type."""
    if raw is None:
        return None
    if field.get("mode") == "REPEATED":
        return [value({**field, "mode": "NULLABLE"}, item["v"]) for item in raw]
    kind = field["type"]
    if kind in ("INTEGER", "INT64"):
        return int(raw)
    if kind in ("FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"):
        return float(raw)
    if kind in ("BOOLEAN", "BOOL"):
        return raw == "true"
    if kind == "TIMESTAMP":
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    return raw


def rows(answer: dict) -> list[dict[str, Any]]:
    fields = answer.get("schema", {}).get("fields", [])
    return [{f["name"]: value(f, cell["v"]) for f, cell in zip(fields, row["f"])} for row in answer.get("rows", [])]


class Warehouse:
    """`token` gives an access token; by default, one traded for `key`'s."""

    def __init__(self, caller: Caller, key: dict, *, token: Callable[[], str] | None = None):
        self.caller, self.project = caller, key["project_id"]
        self.location = "EU"
        self.token = token or GoogleToken(caller, key)

    def _call(self, method: str, url: str, body: dict | None = None) -> dict:
        request = Request(method, url, {"Authorization": f"Bearer {self.token()}",
                                        "Content-Type": "application/json"},
                          json.dumps(body).encode() if body is not None else None, repeatable=True)
        answer = self.caller.call(PLUGIN, "query", request)
        payload = answer.json() or {}
        if not answer.ok:
            message = (payload.get("error") or {}).get("message", "")
            raise Refused(PLUGIN, "query", f"HTTP {answer.status} {message}".rstrip())
        return payload

    def query(self, sql: str) -> list[dict[str, Any]]:
        """The query's rows, every page of them."""
        base = f"{API}/projects/{quote(self.project)}/queries"
        answer = self._call("POST", base, {"query": sql, "useLegacySql": False, "timeoutMs": WAIT_MS,
                                           "location": self.location})
        job = answer.get("jobReference", {}).get("jobId", "")
        polls = 0
        while not answer.get("jobComplete"):
            polls += 1
            if polls > POLLS:
                raise Refused(PLUGIN, "query", f"the query {job} did not finish")
            answer = self._call("GET", f"{base}/{quote(job)}?" + urlencode(
                {"location": self.location, "timeoutMs": WAIT_MS}))
        found = rows(answer)
        while answer.get("pageToken"):
            answer = self._call("GET", f"{base}/{quote(job)}?" + urlencode(
                {"location": self.location, "pageToken": answer["pageToken"]}))
            found += rows(answer)
        return found
