"""Steps for the trends page: its queries on fixture rows (local_bigquery.py),
and the app answering pubtest's HTTP steps."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit, urlunsplit

import pytest
from pubtest.http import asgi
from pytest_bdd import given, parsers, scenarios, when

from observability import links, rules, senders, thresholds
from observability.config import Dataset
from observability.page.app import create_app
from observability.page.queries import signal, trends

from .local_bigquery import DAY, Warehouse
from .shown import shown, table

scenarios("../features/page.feature")

NOW = datetime.fromisoformat(f"{DAY}T10:30:00").replace(tzinfo=timezone.utc)


@pytest.fixture
def warehouse() -> Warehouse:
    w = Warehouse()
    w.signals([])
    return w


@pytest.fixture
def page() -> dict:
    return {"datasets": [], "senders": "", "down": False, "signal_pages": True}


@pytest.fixture
def http_client(warehouse: Warehouse, page: dict):
    """The app as the Givens left it, made for each request."""

    def load():
        if page["down"]:
            raise RuntimeError("no answer")
        return read(warehouse, page)

    def send(method, path, headers, body):
        loader = (lambda r, s, t: read_signal(warehouse, page, r, s, t)) if page["signal_pages"] else None
        # An ASGI server decodes the path it hands the app; pubtest 0.2.1's asgi() does not yet.
        url = urlsplit(path)
        path = urlunsplit(url._replace(path=unquote(url.path)))
        return asgi(create_app(load, loader))(method, path, headers, body)

    return send


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, page: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)
    page["datasets"].append(Dataset(dataset))


@given(parsers.parse('the senders are "{text}"'))
def senders_are(page: dict, text: str) -> None:
    page["senders"] = text


@given(parsers.parse('the open signal "{rule}" for "{subject}" since {clock}'))
def open_signal(warehouse: Warehouse, rule: str, subject: str, clock: str) -> None:
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{clock}:00", "evidence": {"dropped": 3}}])


@given(parsers.parse('the open signal "{rule}" for "{subject}" since {clock}, with evidence "{pairs}"'))
def open_signal_with(warehouse: Warehouse, rule: str, subject: str, clock: str, pairs: str) -> None:
    evidence = dict(pair.split("=", 1) for pair in pairs.split())
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{clock}:00", "evidence": evidence}])


@given(parsers.parse('the signal "{rule}" for "{subject}" from {start} to {end}'))
def ended_signal(warehouse: Warehouse, rule: str, subject: str, start: str, end: str) -> None:
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{start}:00", "severity": "critical"},
                       {"rule_id": rule, "subject": subject, "started_at": f"{start}:00", "ended_at": f"{end}:00",
                        "severity": "critical"}])


@given("no dataset and no senders")
def nothing(warehouse: Warehouse, page: dict) -> None:
    warehouse.load("calls_empty", "empty")
    page["datasets"], page["senders"] = [Dataset("calls_empty")], ""


@given("BigQuery doesn't answer")
def down(page: dict) -> None:
    page["down"] = True


@given("an app with no signal loader")
def no_loader(page: dict) -> None:
    page["signal_pages"] = False


def read(warehouse: Warehouse, page: dict):
    expected = senders.parse(page["senders"], page["datasets"])
    silent = {tier: timedelta(minutes=numbers["silent_minutes"]) for tier, numbers in thresholds.tiers("").items()}
    return trends(warehouse.run, page["datasets"], expected, NOW, silent)


def read_signal(warehouse: Warehouse, page: dict, rule_id: str, subject: str, started: datetime):
    if page["down"]:
        raise RuntimeError("no answer")
    return signal(warehouse.run, page["datasets"], rules.load(), rule_id, subject, started, NOW)


@when("the page's plugins are read at 10:30")
def read_plugins(ctx, warehouse: Warehouse, page: dict) -> None:
    ctx.attempt(lambda: table(read(warehouse, page).plugins, ordered=True))


@when("the page's senders are read at 10:30")
def read_senders(ctx, warehouse: Warehouse, page: dict) -> None:
    ctx.attempt(lambda: table([vars(s) for s in read(warehouse, page).senders], ordered=True))


@when(parsers.parse('the page times of "{who}" are read at 10:30'))
def read_page_times(ctx, warehouse: Warehouse, page: dict, who: str) -> None:
    project, prefix = who.split("/")
    ctx.attempt(lambda: table(read(warehouse, page).page_times[(project, prefix)], ordered=True))


@when("the page's signals are read at 10:30")
def read_signals(ctx, warehouse: Warehouse, page: dict) -> None:
    def listed():
        seen = read(warehouse, page)
        return {name: [f"{r['rule_id']} {r['subject']}" for r in rows]
                for name, rows in (("open", seen.open_signals), ("recent", seen.recent_signals))}

    ctx.attempt(listed)


@when(parsers.parse('the page of "{rule}" for "{subject}" since {clock} is read at 10:30'))
def read_signal_page(ctx, warehouse: Warehouse, page: dict, rule: str, subject: str, clock: str) -> None:
    started = datetime.fromisoformat(f"{DAY}T{clock}:00").replace(tzinfo=timezone.utc)

    def view() -> dict:
        found = read_signal(warehouse, page, rule, subject, started)
        return {"trend": " ".join(f"{shown(r['bucket'])}={float(r['value']):g}" for r in found.trend),
                "context": found.context,
                "buckets": " ".join(shown(r["bucket"]) for r in found.rows),
                "history": ", ".join(f"{shown(r['started_at'])} {shown(r['ended_at']) or 'open'}"
                                     for r in found.history)}

    ctx.attempt(view)


@when("what uvicorn runs is imported")
def imported(ctx) -> None:
    ctx.attempt(lambda: importlib.reload(importlib.import_module("observability.page.main")).app)


def moment_of(text: str) -> datetime:
    return datetime.fromisoformat(text)


@when(parsers.parse('the path of "{rule}" for "{subject}" since "{started}" is made'))
def path_of(ctx, rule: str, subject: str, started: str) -> None:
    ctx.attempt(lambda: links.signal_path(rule, subject, moment_of(started)))


@when(parsers.parse('the full address of "{rule}" for "{subject}" since "{started}" is made'))
def full_address(ctx, rule: str, subject: str, started: str) -> None:
    ctx.attempt(lambda: links.signal_url(rule, subject, moment_of(started)))


@when(parsers.parse('the moment "{key}" names is read'))
def read_back(ctx, key: str) -> None:
    ctx.attempt(lambda: links.parse_started(key).isoformat())


@when(parsers.parse('the address of "{started}" is written'))
def written(ctx, started: str) -> None:
    ctx.attempt(lambda: links.started_key(moment_of(started)))
