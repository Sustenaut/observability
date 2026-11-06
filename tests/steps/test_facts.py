"""Steps running the facts' SQL on fixture rows (local_bigquery.py)."""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from observability import facts
from observability.config import Dataset

from .local_bigquery import Warehouse

scenarios("../features/facts.feature")


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def ran() -> dict:
    return {"datasets": []}


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, ran: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)
    ran["datasets"].append(Dataset(dataset))


@when(parsers.parse('the fact "{fact}" runs'))
def runs(warehouse: Warehouse, ran: dict, fact: str) -> None:
    ran["rows"] = warehouse.run(facts.load()[fact].union(ran["datasets"]))


def shown(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    return str(value)


@then("its rows are")
def rows_are(ran: dict, datatable: list[list[str]]) -> None:
    columns, *expected = datatable
    got = sorted([shown(row[c]) for c in columns] for row in ran["rows"])
    assert got == sorted(expected), f"{columns}\n{got}"


@when(parsers.parse('a fact file "{name}" reads "{text}"'))
def fact_file(ran: dict, name: str, text: str) -> None:
    try:
        facts.parse(name, text.replace("\\n", "\n"))
    except ValueError as error:
        ran["error"] = str(error)


@then(parsers.parse('reading it fails with "{message}"'))
def fails(ran: dict, message: str) -> None:
    assert ran.get("error") == message
