"""The uptime probe runs through pubtest's `I run`, against pubtest's fake
services: the site it watches, and Slack's chat.postMessage. Here are only
the targets it is given and what it told Slack."""

from __future__ import annotations

import json
import socket

from pytest_bdd import given, parsers, scenarios, then

scenarios("../features/uptime.feature")


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
