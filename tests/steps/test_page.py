"""Steps for the trends page: its queries on fixture rows (local_bigquery.py), and
the app through FastAPI's test client."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from observability import senders
from observability.config import Dataset
from observability.page import main
from observability.page.app import create_app
from observability.page.queries import trends

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


def client(warehouse: Warehouse, page: dict) -> TestClient:
    def load():
        if page["down"]:
            raise RuntimeError("no answer")
        return read(warehouse, page)

    return TestClient(create_app(load), follow_redirects=False)


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
