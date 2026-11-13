"""Steps running each rule's SQL on fixture rows (local_bigquery.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from observability import cli, rules, senders
from observability.config import Dataset

from .local_bigquery import DAY, Warehouse

scenarios("../features/rules.feature")


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def ran() -> dict:
    return {"datasets": [], "senders": {}}


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, ran: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)
    ran["datasets"].append(Dataset(dataset))


@given(parsers.parse('a fresh dataset "{dataset}" holding "{fixture}"'))
def fresh(warehouse: Warehouse, ran: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)


@given("the nightly checks found")
def checks_found(warehouse: Warehouse, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.pubkit_checks([dict(zip(columns, row)) for row in rows])


@given("the convergence engine's walks found")
def walks_found(warehouse: Warehouse, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.need_states([dict(zip(columns, row)) for row in rows])


@given(parsers.parse('the senders are "{text}"'))
def senders_are(ran: dict, text: str) -> None:
    ran["senders_text"] = text


def moment(clock: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{clock}:00").replace(tzinfo=timezone.utc)


def run(warehouse: Warehouse, ran: dict, rule: str, clock: str, datasets: list[Dataset]) -> None:
    expected = senders.parse(ran.get("senders_text", ""), datasets)
    ran["rows"] = warehouse.run(rules.load()[rule].sql(datasets, senders.always(expected), moment(clock)))


@when(parsers.parse('the rule "{rule}" runs at {clock} over "{dataset}"'))
def runs_over(warehouse: Warehouse, ran: dict, rule: str, clock: str, dataset: str) -> None:
    run(warehouse, ran, rule, clock, [Dataset(dataset)])


@when(parsers.re(r'the rule "(?P<rule>[a-z_]+)" runs at (?P<clock>\d\d:\d\d)$'))
def runs(warehouse: Warehouse, ran: dict, rule: str, clock: str) -> None:
    run(warehouse, ran, rule, clock, ran["datasets"])


def shown(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    return str(value)


@then("it finds")
def finds(ran: dict, datatable: list[list[str]]) -> None:
    columns, *expected = datatable
    got = sorted([shown(row[c]) for c in columns] for row in ran["rows"])
    assert got == sorted(expected), f"{columns}\n{got}"


@then("it finds nothing")
def finds_nothing(ran: dict) -> None:
    assert ran["rows"] == [], ran["rows"]


@when(parsers.parse('a rule file "{name}" reads "{text}"'))
def rule_file(ran: dict, name: str, text: str) -> None:
    try:
        rules.parse(name, yaml.safe_load(text))
    except ValueError as error:
        ran["error"] = str(error)


@then(parsers.parse('reading it fails with "{message}"'))
def fails(ran: dict, message: str) -> None:
    assert ran.get("error", "").startswith(message), ran.get("error")


@when("I list the rules")
def list_rules(ran: dict, capsys) -> None:
    assert cli.main(["rules"]) == 0
    ran["out"] = capsys.readouterr().out


@then(parsers.parse('the list has "{text}"'))
def list_has(ran: dict, text: str) -> None:
    assert text.replace("\\t", "\t") in ran["out"], ran["out"]
