"""The uptime probe runs through pubtest's `I run`, against pubtest's fake
services: the site it watches, Slack's chat.postMessage, and, when it records,
BigQuery's insertAll and the metadata server's token. Here are only
the targets it is given and what it told Slack."""

from __future__ import annotations

import json
import socket

from pubtest.steps.fakes import fake
from pytest_bdd import given, parsers, scenarios, then

scenarios("../features/uptime.feature", "../features/uptime_recording.feature")

INSERT = "POST /projects/example/datasets/observability/tables/uptime_probes/insertAll"


def targets(ctx, monkeypatch, target: dict) -> None:
    """UPTIME_TARGETS, with one more target."""
    ctx.targets = [*getattr(ctx, "targets", []), target]
    monkeypatch.setenv("UPTIME_TARGETS", json.dumps(ctx.targets))


@given(parsers.parse('the probe posts to the "{name}" service\'s "{path}"'))
def slack_api(ctx, monkeypatch, name: str, path: str) -> None:
    monkeypatch.setenv("UPTIME_SLACK_API", f"{ctx.fakes[name].url}{path}")


@given(parsers.re(r'the target "(?P<name>[^"]+)" at "(?P<path>[^"]+)"'
                  r'(?: expecting (?P<status>\d+))?(?: alerting "(?P<channel>[^"]+)")?$'))
def one_target(ctx, monkeypatch, name: str, path: str, status: str | None, channel: str | None) -> None:
    target = {"name": name, "url": f"{ctx.fakes['site'].url}{path}", "expect_status": int(status or 200)}
    if channel:
        target["channel"] = channel
    targets(ctx, monkeypatch, target)


@given(parsers.parse('the target "{name}" at a port nothing listens on'))
def refused(ctx, monkeypatch, name: str) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    targets(ctx, monkeypatch, {"name": name, "url": f"http://127.0.0.1:{port}/"})


@given(parsers.parse('the target "{name}" at a port that takes the request and never answers'))
def silent(ctx, monkeypatch, name: str) -> None:
    listening = socket.socket()
    listening.bind(("127.0.0.1", 0))
    listening.listen(8)
    ctx.cleanup(listening.close)
    targets(ctx, monkeypatch, {"name": name, "url": f"http://127.0.0.1:{listening.getsockname()[1]}/"})


@then(parsers.parse('Slack was told "{text}" in "{channel}"'))
def told_in(ctx, text: str, channel: str) -> None:
    posts = [json.loads(r["body"]) for r in ctx.fakes["slack"].requests]
    assert any(text in post["text"] and post["channel"] == channel for post in posts), posts


def only(ctx, monkeypatch, name: str, request: str, status: int, body: dict) -> None:
    """The fake service's one answer to the request, in place of any before it."""
    fake(ctx, monkeypatch, name).answers[request] = [(status, json.dumps(body), {})]


@given(parsers.parse('the metadata server gives the token "{token}"'))
def metadata_token(ctx, monkeypatch, token: str) -> None:
    only(ctx, monkeypatch, "metadata", "GET /token", 200, {"access_token": token, "expires_in": 3599})
    monkeypatch.setenv("UPTIME_TOKEN_API", f"{ctx.fakes['metadata'].url}/token")


@given("the metadata server gives no token")
def no_token(ctx, monkeypatch) -> None:
    only(ctx, monkeypatch, "metadata", "GET /token", 200, {})


@given("BigQuery takes every row")
def takes_rows(ctx, monkeypatch) -> None:
    only(ctx, monkeypatch, "bigquery", INSERT, 200, {"kind": "bigquery#tableDataInsertAllResponse"})
    monkeypatch.setenv("UPTIME_BIGQUERY_API", ctx.fakes["bigquery"].url)


@given(parsers.parse('BigQuery refuses every row as "{reason}"'))
def refuses_rows(ctx, monkeypatch, reason: str) -> None:
    only(ctx, monkeypatch, "bigquery", INSERT, 200,
         {"insertErrors": [{"index": 0, "errors": [{"reason": reason, "message": "no such field"}]}]})


@given(parsers.parse("BigQuery answers every insert with {status:d}"))
def insert_fails(ctx, monkeypatch, status: int) -> None:
    only(ctx, monkeypatch, "bigquery", INSERT, status, {"error": {"message": "backend error"}})


def sent_rows(ctx) -> list[dict]:
    bodies = [json.loads(r["body"]) for r in ctx.fakes["bigquery"].requests]
    return [{"insertId": row["insertId"], **row["json"]} for body in bodies for row in body["rows"]]


def shown(value: object) -> str:
    """A row's value as a feature's table writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@then("BigQuery was sent the rows:")
def sent(ctx, datatable: list[list[str]]) -> None:
    columns, *wanted = datatable
    got = [{c: shown(row.get(c)) for c in columns} for row in sent_rows(ctx)]
    assert got == [dict(zip(columns, row)) for row in wanted], got
    for row in sent_rows(ctx):
        assert row["url"].startswith(ctx.fakes["site"].url) or row["url"].startswith("http://127.0.0.1:"), row
        assert row["probed_at"].endswith("+00:00") and isinstance(row["elapsed_ms"], int), row


@then(parsers.parse('every row BigQuery was sent names an execution starting "{prefix}"'))
def execution_named(ctx, prefix: str) -> None:
    rows = sent_rows(ctx)
    assert rows and all(row["execution"].startswith(prefix) for row in rows), rows
