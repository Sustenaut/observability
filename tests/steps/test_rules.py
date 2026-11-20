"""Steps running each rule's SQL on fixture rows (local_bigquery.py)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, when

from observability import cli, rules, senders, thresholds
from observability.config import Dataset

from .local_bigquery import DAY, Warehouse
from .shown import table

scenarios("../features/rules.feature")


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def ran() -> dict:
    return {"datasets": [], "senders_text": "", "thresholds": ""}


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, ran: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)
    ran["datasets"].append(Dataset(dataset))


@given(parsers.parse('a fresh dataset "{dataset}" holding "{fixture}"'))
def fresh(warehouse: Warehouse, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)


@given("the nightly checks found")
def checks_found(warehouse: Warehouse, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.pubrules_checks([dict(zip(columns, row)) for row in rows])


@given("the uptime probe recorded")
def probes_recorded(warehouse: Warehouse, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.uptime_probes([{c: v for c, v in zip(columns, row) if v} for row in rows])


@given("the convergence engine's walks found")
def walks_found(warehouse: Warehouse, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.need_states([dict(zip(columns, row)) for row in rows])


@given(parsers.parse('the senders are "{text}"'))
def senders_are(ran: dict, text: str) -> None:
    ran["senders_text"] = text


@given(parsers.parse('the thresholds are "{text}"'))
def thresholds_are(ran: dict, text: str) -> None:
    ran["thresholds"] = text


def cell(column: str, text: str) -> object:
    """A cycle's value as a feature's table writes it."""
    if column == "storage_ok":
        return text == "true"
    return text


@given(parsers.parse('the ingest pod\'s cycles for "{dataset}" were'))
def ingest_cycles(warehouse: Warehouse, dataset: str, datatable: list[list[str]]) -> None:
    columns, *rows = datatable
    warehouse.hold(dataset, {"status": [
        {"kind": "ingest", "sender": "ingest-0", **{c: cell(c, v) for c, v in zip(columns, row) if v}}
        for row in rows]})


def moment(clock: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{clock}:00").replace(tzinfo=timezone.utc)


def run(ctx, warehouse: Warehouse, ran: dict, rule: str, clock: str, datasets: list[Dataset]) -> None:
    def found() -> list[dict]:
        expected = senders.parse(ran["senders_text"], datasets)
        every = thresholds.effective(ran["thresholds"], rules.load())
        return table(warehouse.run(every[rule].sql(datasets, senders.always(expected), moment(clock))))

    ctx.attempt(found)


@when(parsers.parse('the rule "{rule}" runs at {clock} over "{dataset}"'))
def runs_over(ctx, warehouse: Warehouse, ran: dict, rule: str, clock: str, dataset: str) -> None:
    run(ctx, warehouse, ran, rule, clock, [Dataset(name) for name in dataset.split('" and "')])


@when(parsers.re(r'the rule "(?P<rule>[a-z_]+)" runs at (?P<clock>\d\d:\d\d)$'))
def runs(ctx, warehouse: Warehouse, ran: dict, rule: str, clock: str) -> None:
    run(ctx, warehouse, ran, rule, clock, ran["datasets"])


@when(parsers.parse('a rule file "{name}" reads "{text}"'))
def rule_file(ctx, name: str, text: str) -> None:
    read = yaml.safe_load(text)
    ctx.attempt(lambda: rules.parse(name, read))


@when(parsers.parse('the rule file "{name}" is rendered with the thresholds "{text}"'))
def rendered(ctx, name: str, text: str) -> None:
    rule = thresholds.apply({name: ctx.result}, {name: yaml.safe_load(text)})[name]
    now = moment("10:30")
    ctx.attempt(lambda: {"query": rule.sql([], [], now), "trend": rule.trend_sql([], 5, now),
                         "threshold": rule.threshold})


@when("the rules are listed")
def list_rules(ctx) -> None:
    ctx.attempt(lambda: sys.exit(cli.main(["rules"])))
