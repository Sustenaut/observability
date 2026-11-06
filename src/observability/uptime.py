"""The uptime probe: whether each site answers, seen from outside its server.

It runs on GitHub Actions every five minutes (.github/workflows/uptime.yml),
off the server it watches, so it still reports when that server is down.
A target is down only after two runs in a row have failed, and each run
tries a failing target twice before counting it. The run's state, each
target's failures in a row and whether it is down, is kept between runs in
uptime-state.json in the working directory, which the workflow caches.

Which sites are probed is configuration, never in this repository:
UPTIME_TARGETS is a JSON list of {"name", "url", "expect_status",
"channel"}. Going down and recovering are posted by the Sustenaut Slack bot
(SUSTENAUT_SLACK_BOT_TOKEN) to the target's channel, or, for a target with
none, to UPTIME_SLACK_CHANNEL; each is a channel's or a person's id. It
posts directly: the integrations service, which posts for everything
else, runs on the server being watched.

    python -m observability.uptime
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

TARGETS = "UPTIME_TARGETS"
# The environment variable that holds the bot's credential (its name, not the value).
BOT_VARIABLE = "SUSTENAUT_SLACK_BOT_TOKEN"
CHANNEL = "UPTIME_SLACK_CHANNEL"
# Slack's chat.postMessage; the suite points it at a local stand-in.
SLACK_API = "UPTIME_SLACK_API"
POST_MESSAGE = "https://slack.com/api/chat.postMessage"
# Kept between runs, always here: no path to it is taken from outside.
STATE = Path("uptime-state.json")
KEYS = {"name", "url", "expect_status", "channel"}
# Runs in a row that must fail before a target is down.
DOWN_AFTER = 2
USER_AGENT = "Sustenaut observability uptime probe"


@dataclass(frozen=True)
class Target:
    name: str
    url: str
    expect_status: int = 200
    # Where its alerts go; None for UPTIME_SLACK_CHANNEL.
    channel: str | None = None


@dataclass(frozen=True)
class Result:
    target: Target
    up: bool
    detail: str


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is the answer to compare, not a page to follow."""

    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def targets(text: str) -> list[Target]:
    """The targets UPTIME_TARGETS lists, each checked."""
    try:
        listed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{TARGETS} is not JSON: {error}") from None
    if not isinstance(listed, list) or not listed:
        raise ValueError(f"{TARGETS} must be a JSON list of targets")
    found = []
    for entry in listed:
        if not isinstance(entry, dict) or set(entry) - KEYS:
            raise ValueError(f'{TARGETS}: each target is {{"name", "url", "expect_status", "channel"}}, '
                             f'not {json.dumps(entry)}')
        name, url, status = entry.get("name"), entry.get("url"), entry.get("expect_status", 200)
        if not isinstance(name, str) or not name or not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ValueError(f"{TARGETS}: a target needs a name and an http(s) url: {json.dumps(entry)}")
        if not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError(f"{TARGETS}: {name}'s expect_status must be an HTTP status")
        channel = entry.get("channel")
        if channel is not None and (not isinstance(channel, str) or not channel.strip()):
            raise ValueError(f"{TARGETS}: {name}'s channel must be a channel's or a person's id")
        found.append(Target(name, url, status, channel))
    if len({t.name for t in found}) != len(found):
        raise ValueError(f"{TARGETS} names a target twice")
    return found


def attempt(target: Target, timeout: float) -> Result:
    """One request: up when the target answers with the status it should."""
    request = urllib.request.Request(target.url, headers={"User-Agent": USER_AGENT})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        return Result(target, False, f"no answer: {reason}")
    if status != target.expect_status:
        return Result(target, False, f"HTTP {status}, not {target.expect_status}")
    return Result(target, True, f"HTTP {status}")


def probe(target: Target, timeout: float, pause: float) -> Result:
    """The target's answer, tried once more after a pause if it fails."""
    result = attempt(target, timeout)
    if not result.up:
        time.sleep(pause)
        result = attempt(target, timeout)
    return result


def advance(state: dict, results: list[Result]) -> tuple[dict, list[tuple[str, Result]]]:
    """The state after this run's results, and what changed: a target gone
    down, or one recovered. Targets no longer listed are forgotten."""
    after, changes = {}, []
    for result in results:
        before = state.get(result.target.name, {})
        failures = 0 if result.up else int(before.get("failures", 0)) + 1
        down = failures >= DOWN_AFTER
        if down and not before.get("down"):
            changes.append(("down", result))
        elif before.get("down") and not down:
            changes.append(("recovered", result))
        after[result.target.name] = {"failures": failures, "down": down}
    return after, changes


def message(changes: list[tuple[str, Result]]) -> str:
    lines = []
    for change, result in changes:
        t = result.target
        if change == "down":
            lines.append(f":red_circle: {t.name} is down: {result.detail} from {t.url} in {DOWN_AFTER} runs in a row")
        else:
            lines.append(f":large_green_circle: {t.name} has recovered: {result.detail} from {t.url}")
    return "\n".join(lines)


def by_channel(changes: list[tuple[str, Result]], default: str) -> tuple[dict, list[str]]:
    """The changes, grouped by where each is posted: its target's channel, or
    the default. The names of those with neither go apart."""
    groups: dict[str, list[tuple[str, Result]]] = {}
    unrouted = []
    for change in changes:
        channel = change[1].target.channel or default
        if channel:
            groups.setdefault(channel, []).append(change)
        else:
            unrouted.append(change[1].target.name)
    return groups, unrouted


def post(token: str, channel: str, text: str, timeout: float) -> None:
    """Post as the bot. Slack answers 200 to a post it refuses, with "ok"
    false and its reason, so the answer is read, not just its status."""
    body = json.dumps({"channel": channel, "text": text}).encode()
    request = urllib.request.Request(
        os.environ.get(SLACK_API, POST_MESSAGE), data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8",
                 "User-Agent": USER_AGENT})
    with _OPENER.open(request, timeout=timeout) as response:
        answer = json.loads(response.read() or b"{}")
    if not answer.get("ok"):
        raise OSError(f"Slack refused the post: {answer.get('error', 'no reason given')}")


def read_state(path: Path) -> dict:
    """The last run's state; none when there is no file or it is unreadable,
    as on the first run or after the cache was evicted."""
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="observability.uptime", description=__doc__.split("\n\n")[0])
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for an answer (default 10)")
    parser.add_argument("--pause", type=float, default=5.0, help="seconds before trying a failing target again (default 5)")
    args = parser.parse_args(argv)
    try:
        listed = targets(os.environ.get(TARGETS, ""))
    except ValueError as error:
        print(f"uptime: {error}", file=sys.stderr)
        return 2
    results = [probe(target, args.timeout, args.pause) for target in listed]
    state, changes = advance(read_state(STATE), results)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    for result in results:
        mark = "up" if result.up else ("DOWN" if state[result.target.name]["down"] else "failing")
        print(f"{mark}\t{result.target.name}\t{result.detail}")
    failed = False
    if changes:
        groups, unrouted = by_channel(changes, os.environ.get(CHANNEL, ""))
        if unrouted:
            print(f"uptime: no {CHANNEL}, and no channel of their own, for {', '.join(unrouted)}, "
                  "so nothing was posted for them", file=sys.stderr)
        token = os.environ.get(BOT_VARIABLE, "")
        if groups and not token:
            print(f"uptime: no {BOT_VARIABLE}, so nothing was posted to Slack", file=sys.stderr)
        elif groups:
            for channel, group in groups.items():
                try:
                    post(token, channel, message(group), args.timeout)
                except (urllib.error.URLError, OSError, ValueError) as error:
                    print(f"uptime: posting to Slack failed, for {channel}: {error}", file=sys.stderr)
                    failed = True
    down = sorted(name for name, entry in state.items() if entry["down"])
    if down:
        print(f"uptime: down: {', '.join(down)}", file=sys.stderr)
    return 1 if down or failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
