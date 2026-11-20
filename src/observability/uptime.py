"""The uptime probe: whether each site answers, seen from outside its server.

It runs off the server it watches, so it still reports when that server is
down, and tries a failing target twice before counting it. It runs one of
two ways:

- **Recording**, with UPTIME_TABLE set (project.dataset.table): as the Cloud
  Run job observability-uptime, which Cloud Scheduler starts every five
  minutes. Each run appends one row per target to that BigQuery table, up or
  not, and keeps no state: the rules uptime_down and uptime_silent read the
  rows, and the notifier posts what they find. It reaches BigQuery as the
  account attached to the job, whose token the metadata server gives, so
  there is no key. A run in which any target failed exits 1, which Google's
  backup alert counts (shared-infra's infra/uptime.tf).
- **Posting**, without it: on GitHub Actions (.github/workflows/uptime.yml),
  until the recording path has proven itself. A target is down only after
  two runs in a row have failed. The run's state, each target's failures in
  a row and whether it is down, is kept between runs in uptime-state.json in
  the working directory, which the workflow caches.

Which sites are probed is configuration, never in this repository:
UPTIME_TARGETS is a JSON list of {"name", "url", "expect_status",
"channel"}. Going down and recovering are posted by the Sustenaut Slack bot
(SUSTENAUT_SLACK_BOT_TOKEN) to the target's channel, or, for a target with
none, to UPTIME_SLACK_CHANNEL; each is a channel's or a person's id. It
posts directly: the integrations service, which posts for everything
else, runs on the server being watched. Recording posts nothing.

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
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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
# Recording: the table rows go to, as project.dataset.table.
TABLE = "UPTIME_TABLE"
INSERT_ALL = "https://bigquery.googleapis.com/bigquery/v2/projects/{}/datasets/{}/tables/{}/insertAll"
# The token of the account attached to the Cloud Run job.
METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
# The suite points these at local stand-ins.
BIGQUERY_API = "UPTIME_BIGQUERY_API"
TOKEN_API = "UPTIME_TOKEN_API"
# The run, as Cloud Run names it; every target probed in it shares it.
EXECUTION = "CLOUD_RUN_EXECUTION"


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
    # The last answer's HTTP status; None when there was none.
    status: int | None = None
    attempts: int = 1
    elapsed_ms: int = 0
    # When the last try ended.
    at: datetime | None = None


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
    started = time.monotonic()

    def result(up: bool, detail: str, status: int | None) -> Result:
        return Result(target, up, detail, status, 1, round((time.monotonic() - started) * 1000),
                      datetime.now(timezone.utc))

    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        return result(False, f"no answer: {reason}", None)
    if status != target.expect_status:
        return result(False, f"HTTP {status}, not {target.expect_status}", status)
    return result(True, f"HTTP {status}", status)


def probe(target: Target, timeout: float, pause: float) -> Result:
    """The target's answer, tried once more after a pause if it fails."""
    result = attempt(target, timeout)
    if not result.up:
        time.sleep(pause)
        again = attempt(target, timeout)
        result = Result(again.target, again.up, again.detail, again.status, 2, again.elapsed_ms, again.at)
    return result


def probe_all(listed: list[Target], timeout: float, pause: float) -> list[Result]:
    """Every target's answer, all at once, so a run takes as long as its slowest
    target, not the sum of them; in the order listed."""
    with ThreadPoolExecutor(max_workers=min(16, len(listed))) as pool:
        return list(pool.map(lambda target: probe(target, timeout, pause), listed))


def row(result: Result, execution: str) -> dict:
    """The table's row for one result (shared-infra's schemas/observability/uptime_probes.json)."""
    t = result.target
    return {"probed_at": (result.at or datetime.now(timezone.utc)).isoformat(), "execution": execution,
            "target": t.name, "url": t.url, "up": result.up, "status": result.status,
            "expect_status": t.expect_status, "detail": result.detail, "attempts": result.attempts,
            "elapsed_ms": result.elapsed_ms}


def table_parts(text: str) -> tuple[str, str, str]:
    """UPTIME_TABLE's project, dataset and table."""
    parts = text.split(".")
    if len(parts) != 3 or not all(part.replace("-", "").replace("_", "").isalnum() for part in parts):
        raise ValueError(f"{TABLE} is project.dataset.table, not {text!r}")
    return parts[0], parts[1], parts[2]


def access_token(timeout: float) -> str:
    """The attached account's token, from the metadata server: no key anywhere."""
    request = urllib.request.Request(os.environ.get(TOKEN_API, METADATA_TOKEN),
                                     headers={"Metadata-Flavor": "Google", "User-Agent": USER_AGENT})
    with _OPENER.open(request, timeout=timeout) as response:
        token = json.loads(response.read() or b"{}").get("access_token")
    if not isinstance(token, str) or not token:
        raise OSError("the metadata server gave no access token")
    return token


def record(table: tuple[str, str, str], rows: list[dict], timeout: float) -> None:
    """Append the rows (tabledata.insertAll). Each row's insertId is its run and
    target, so a request BigQuery took but didn't answer, sent again, is one
    row. BigQuery answers 200 with insertErrors for rows it refused, so the
    answer is read, not just its status."""
    url = os.environ.get(BIGQUERY_API, "").rstrip("/")
    url = (f"{url}/projects/{quote(table[0])}/datasets/{quote(table[1])}/tables/{quote(table[2])}/insertAll"
           if url else INSERT_ALL.format(*(quote(part) for part in table)))
    body = json.dumps({"skipInvalidRows": False, "ignoreUnknownValues": False,
                       "rows": [{"insertId": f"{r['execution']}/{r['target']}", "json": r} for r in rows]}).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {access_token(timeout)}", "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    with _OPENER.open(request, timeout=timeout) as response:
        answer = json.loads(response.read() or b"{}")
    errors = answer.get("insertErrors") or []
    if errors:
        reasons = sorted({e.get("reason", "?") for entry in errors for e in entry.get("errors", [])})
        raise OSError(f"BigQuery refused {len(errors)} of {len(rows)} rows: {', '.join(reasons) or 'no reason given'}")


def recording(table_text: str, listed: list[Target], args: argparse.Namespace) -> int:
    """One recorded run: every target probed, every result appended."""
    try:
        table = table_parts(table_text)
    except ValueError as error:
        print(f"uptime: {error}", file=sys.stderr)
        return 2
    results = probe_all(listed, args.timeout, args.pause)
    execution = os.environ.get(EXECUTION) or f"local-{uuid.uuid4().hex}"
    for result in results:
        print(f"{'up' if result.up else 'failing'}\t{result.target.name}\t{result.detail}")
    try:
        record(table, [row(result, execution) for result in results], args.timeout)
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"uptime: recording to {table_text} failed: {error}", file=sys.stderr)
        return 1
    print(f"uptime: recorded {len(results)} targets in {table_text}")
    failing = [result.target.name for result in results if not result.up]
    if failing:
        print(f"uptime: failing: {', '.join(failing)}", file=sys.stderr)
    return 1 if failing else 0


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
    if os.environ.get(TABLE):
        return recording(os.environ[TABLE], listed, args)
    results = probe_all(listed, args.timeout, args.pause)
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
