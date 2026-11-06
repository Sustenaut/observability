"""Steps running the uptime probe, `python -m observability.uptime`, against a
local site and a local stand-in for Slack's chat.postMessage."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/uptime.feature")

ROOT = Path(__file__).resolve().parents[2]


class Site(BaseHTTPRequestHandler):
    """/ok, /broken, /moved, /slow, /flaky; POST /api/chat.postMessage is Slack."""

    posts: list[dict]
    flaky: dict
    slack: dict

    def log_message(self, *args) -> None:  # noqa: ANN002
        pass

    def answer(self, status: int, headers: dict | None = None, body: bytes = b"") -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ok":
            self.answer(200)
        elif self.path == "/broken":
            self.answer(503)
        elif self.path == "/moved":
            self.answer(302, {"Location": "/ok"})
        elif self.path == "/flaky":
            self.flaky["n"] += 1
            self.answer(503 if self.flaky["n"] == 1 else 200)
        else:  # /slow
            time.sleep(1)
            self.answer(200)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.posts.append({**json.loads(self.rfile.read(length)), "auth": self.headers["Authorization"]})
        self.answer(self.slack["status"], body=self.slack["body"])


@pytest.fixture
def site():
    handler = type("Handler", (Site,), {"posts": [], "flaky": {"n": 0},
                                         "slack": {"status": 200, "body": b'{"ok": true}'}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"base": f"http://127.0.0.1:{server.server_port}", "handler": handler}
    server.shutdown()
    server.server_close()


@pytest.fixture
def probe(site, tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("UPTIME_")}
    env = {k: v for k, v in env.items() if k != "SUSTENAUT_SLACK_BOT_TOKEN"}
    env["SUSTENAUT_SLACK_BOT_TOKEN"] = "xoxb-test"
    env["UPTIME_SLACK_CHANNEL"] = "C0TEST"
    env["UPTIME_SLACK_API"] = f"{site['base']}/api/chat.postMessage"
    return {"env": env, "targets": [], "state": tmp_path / "uptime-state.json", "cwd": tmp_path}


@given(parsers.parse('a site that answers "/ok" with 200, "/broken" with 503 and "/moved" with a redirect'))
def a_site(site) -> None:
    pass


def add(site, probe: dict, name: str, path: str, status: int = 200, channel: str | None = None) -> None:
    target = {"name": name, "url": f"{site['base']}{path}", "expect_status": status}
    if channel:
        target["channel"] = channel
    probe["targets"].append(target)


@given(parsers.parse('the targets "{a}" at "{a_path}" and "{b}" at "{b_path}"'))
def two_targets(site, probe: dict, a: str, a_path: str, b: str, b_path: str) -> None:
    add(site, probe, a, a_path)
    add(site, probe, b, b_path)


@given(parsers.re(r'the target "(?P<name>[^"]+)" at "(?P<path>[^"]+)"'
                  r'(?: expecting (?P<status>\d+))?(?: alerting "(?P<channel>[^"]+)")?$'))
def one_target(site, probe: dict, name: str, path: str, status: str | None, channel: str | None) -> None:
    add(site, probe, name, path, int(status or 200), channel)


@given(parsers.parse('the target "{name}" at a port nothing listens on'))
def refused(probe: dict, name: str) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    probe["targets"].append({"name": name, "url": f"http://127.0.0.1:{port}/"})


@given(parsers.parse('the last run left "{name}" with {failures:d} failures, {how}'))
def last_run(probe: dict, name: str, failures: int, how: str) -> None:
    state = json.loads(probe["state"].read_text()) if probe["state"].exists() else {}
    state[name] = {"failures": failures, "down": how == "down"}
    probe["state"].write_text(json.dumps(state))


@given(parsers.parse('the state file reads "{text}"'))
def state_reads(probe: dict, text: str) -> None:
    probe["state"].write_text(text)


@given(parsers.parse("no {name}"))
def unset(probe: dict, name: str) -> None:
    del probe["env"][name]


@given(parsers.parse("Slack answers {status:d}"))
def slack_status(site, status: int) -> None:
    site["handler"].slack["status"] = status


@given(parsers.parse('Slack refuses the post with "{error}"'))
def slack_refuses(site, error: str) -> None:
    site["handler"].slack["body"] = json.dumps({"ok": False, "error": error}).encode()


@given("Slack answers with no reason")
def slack_no_reason(site) -> None:
    site["handler"].slack["body"] = b"{}"


@given(parsers.parse("UPTIME_TARGETS is '{value}'"))
def targets_are(probe: dict, value: str) -> None:
    probe["raw"] = value


@when("the probe runs")
def runs(probe: dict) -> None:
    probe["env"]["UPTIME_TARGETS"] = probe.get("raw", json.dumps(probe["targets"]))
    probe["env"]["PYTHONPATH"] = str(ROOT / "src")
    probe["done"] = subprocess.run(
        [sys.executable, "-m", "observability.uptime", "--timeout", "0.5", "--pause", "0"],
        capture_output=True, text=True, check=False, env=probe["env"], cwd=probe["cwd"])


@then("it succeeds")
def succeeds(probe: dict) -> None:
    assert probe["done"].returncode == 0, probe["done"].stdout + probe["done"].stderr


@then("it fails")
def fails(probe: dict) -> None:
    assert probe["done"].returncode == 1, probe["done"].stdout + probe["done"].stderr


@then(parsers.parse("it exits with {code:d}"))
def exits(probe: dict, code: int) -> None:
    assert probe["done"].returncode == code, probe["done"].stderr


@then(parsers.parse('it prints "{text}"'))
def prints(probe: dict, text: str) -> None:
    text = text.replace("\\t", "\t")
    assert text in probe["done"].stdout, probe["done"].stdout


@then(parsers.parse('stderr mentions "{text}"'))
def stderr_mentions(probe: dict, text: str) -> None:
    assert text in probe["done"].stderr, probe["done"].stderr


@then(parsers.parse('the state says "{name}" has {failures:d} failures and is {how}'))
def state_says(probe: dict, name: str, failures: int, how: str) -> None:
    state = json.loads(probe["state"].read_text())
    assert state[name] == {"failures": failures, "down": how == "down"}, state


@then(parsers.parse('the state names only "{name}"'))
def state_names(probe: dict, name: str) -> None:
    assert list(json.loads(probe["state"].read_text())) == [name]


@then("nothing was posted to Slack")
def nothing_posted(site) -> None:
    assert site["handler"].posts == []


@then(parsers.parse('Slack was told "{text}"'))
def slack_told(site, text: str) -> None:
    told_in(site, text, "C0TEST")


@then(parsers.parse('Slack was told "{text}" in "{channel}"'))
def told_in(site, text: str, channel: str) -> None:
    posts = site["handler"].posts
    assert any(text in post["text"] and post["channel"] == channel for post in posts), posts
    assert all(post["auth"] == "Bearer xoxb-test" for post in posts), posts


@then(parsers.parse("Slack was posted to {count:d} times"))
def posted_times(site, count: int) -> None:
    assert len(site["handler"].posts) == count, site["handler"].posts
