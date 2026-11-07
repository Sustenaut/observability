"""Steps for the trends page: its queries on fixture rows (local_bigquery.py), and
the app through FastAPI's test client."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from observability import senders  # noqa: I001
from observability.config import Dataset
from observability.page import main
from observability.page.app import create_app
from observability import links, rules
from observability.page.queries import signal, trends

from .local_bigquery import DAY, Warehouse

scenarios("../features/page.feature")

NOW = datetime.fromisoformat(f"{DAY}T10:30:00").replace(tzinfo=timezone.utc)


@pytest.fixture
def warehouse() -> Warehouse:
    w = Warehouse()
    w.signals([])
    return w


@pytest.fixture
def page() -> dict:
    return {"datasets": [], "senders": "", "down": False}


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


def read(warehouse: Warehouse, page: dict):
    expected = senders.parse(page["senders"], page["datasets"])
    return trends(warehouse.run, page["datasets"], expected, NOW)


@when(parsers.parse("the page's trends are read at 10:30"))
def read_trends(warehouse: Warehouse, page: dict) -> None:
    page["trends"] = read(warehouse, page)


def read_signal(warehouse: Warehouse, page: dict, rule_id: str, subject: str, started: datetime):
    if page["down"]:
        raise RuntimeError("no answer")
    return signal(warehouse.run, page["datasets"], rules.load(), rule_id, subject, started, NOW)


def client(warehouse: Warehouse, page: dict) -> TestClient:
    def load():
        if page["down"]:
            raise RuntimeError("no answer")
        return read(warehouse, page)

    return TestClient(create_app(load, lambda r, s, t: read_signal(warehouse, page, r, s, t)),
                      follow_redirects=False)


@when("the page is asked for")
def asked(warehouse: Warehouse, page: dict) -> None:
    page["answer"] = client(warehouse, page).get("/trends/integrations/")


def shown(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    return str(value)


def check(rows: list[dict], datatable: list[list[str]]) -> None:
    columns, *expected = datatable
    got = [[shown(row[c]) for c in columns] for row in rows]
    assert got == expected, f"{columns}\n{got}"


@then("the plugins are")
def plugins_are(page: dict, datatable: list[list[str]]) -> None:
    check(page["trends"].plugins, datatable)


@then("the senders are")
def senders_listed(page: dict, datatable: list[list[str]]) -> None:
    check([vars(s) for s in page["trends"].senders], datatable)


@then(parsers.parse('the page times of "{who}" are'))
def page_times(page: dict, who: str, datatable: list[list[str]]) -> None:
    project, prefix = who.split("/")
    check(page["trends"].page_times[(project, prefix)], datatable)


@then(parsers.parse('the open signals are "{listed}"'))
def open_are(page: dict, listed: str) -> None:
    assert [f"{r['rule_id']} {r['subject']}" for r in page["trends"].open_signals] == [listed]


@then(parsers.parse('the recent signals are "{listed}"'))
def recent_are(page: dict, listed: str) -> None:
    assert [f"{r['rule_id']} {r['subject']}" for r in page["trends"].recent_signals] == [listed]


@then(parsers.parse("it answers {status:d}"))
def answers(page: dict, status: int) -> None:
    assert page["answer"].status_code == status, page["answer"].text


@then(parsers.parse('it shows "{text}"'))
def shows(page: dict, text: str) -> None:
    assert text in page["answer"].text, page["answer"].text


@then("it is never cached and runs no script")
def headers(page: dict) -> None:
    answer = page["answer"]
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert "<script" not in answer.text


@then(parsers.parse('"{path}" leads to "{target}"'))
def leads(warehouse: Warehouse, page: dict, path: str, target: str) -> None:
    answer = client(warehouse, page).get(path)
    assert answer.status_code == 307 and answer.headers["location"] == target


@then("what uvicorn runs imports, with no app until it has its key")
def imports() -> None:
    assert main.app is None


@then(parsers.parse('"{path}" answers ok'))
def health(warehouse: Warehouse, page: dict, path: str) -> None:
    assert client(warehouse, page).get(path).json() == {"status": "ok"}


@given(parsers.parse('the open signal "{rule}" for "{subject}" since {clock}, with evidence "{pairs}"'))
def open_signal_with(warehouse: Warehouse, rule: str, subject: str, clock: str, pairs: str) -> None:
    evidence = dict(pair.split("=", 1) for pair in pairs.split())
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{clock}:00", "evidence": evidence}])


@when(parsers.parse('the page of "{rule}" for "{subject}" since {clock} is read at 10:30'))
def read_signal_page(warehouse: Warehouse, page: dict, rule: str, subject: str, clock: str) -> None:
    started = datetime.fromisoformat(f"{DAY}T{clock}:00").replace(tzinfo=timezone.utc)
    page["signal"] = read_signal(warehouse, page, rule, subject, started)


@then(parsers.re(r'its trend is "(?P<listed>[^"]*)"'))
def trend_is(page: dict, listed: str) -> None:
    got = " ".join(f"{shown(r['bucket'])}={float(r['value']):g}" for r in page["signal"].trend)
    assert got == listed, got


@then(parsers.re(r'its context is "(?P<context>[^"]*)" with buckets "(?P<listed>[^"]*)"'))
def context_is(page: dict, context: str, listed: str) -> None:
    view = page["signal"]
    assert (view.context, " ".join(shown(r["bucket"]) for r in view.rows)) == (context, listed)


@then(parsers.parse('its history is "{listed}"'))
def history_is(page: dict, listed: str) -> None:
    got = ", ".join(f"{shown(r['started_at'])} {shown(r['ended_at']) or 'open'}" for r in page["signal"].history)
    assert got == listed, got


@when(parsers.parse('"{path}" is asked for'))
def asked_path(warehouse: Warehouse, page: dict, path: str) -> None:
    page["answer"] = client(warehouse, page).get(path)


@then(parsers.parse('an app with no signal loader answers 404 for "{path}"'))
def no_loader(path: str) -> None:
    assert TestClient(create_app(lambda: None)).get(path).status_code == 404


def moment_of(text: str) -> datetime:
    return datetime.fromisoformat(text)


@then(parsers.parse('the path of "{rule}" for "{subject}" since "{started}" is "{path}"'))
def path_is(rule: str, subject: str, started: str, path: str) -> None:
    assert links.signal_path(rule, subject, moment_of(started)) == path


@then(parsers.parse('"{key}" reads back as "{started}"'))
def reads_back(key: str, started: str) -> None:
    assert links.parse_started(key) == moment_of(started)
    assert links.started_key(moment_of(started)) == key


@then(parsers.parse('the full address of "{rule}" for "{subject}" since "{started}" is "{url}"'))
def full_address(rule: str, subject: str, started: str, url: str) -> None:
    assert links.signal_url(rule, subject, moment_of(started)) == url


@then(parsers.parse('a rule id "{rule}" has no address'))
def no_address(rule: str) -> None:
    with pytest.raises(ValueError):
        links.signal_path(rule, "x", NOW)
