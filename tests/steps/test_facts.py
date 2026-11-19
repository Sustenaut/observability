"""Steps running the facts' SQL on fixture rows (local_bigquery.py)."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, when

from observability import facts
from observability.config import Dataset

from .local_bigquery import Warehouse
from .shown import table

scenarios("../features/facts.feature")


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def datasets() -> list[Dataset]:
    return []


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, datasets: list[Dataset], dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)
    datasets.append(Dataset(dataset))


@when(parsers.parse('the fact "{fact}" runs'))
def runs(ctx, warehouse: Warehouse, datasets: list[Dataset], fact: str) -> None:
    ctx.attempt(lambda: table(warehouse.run(facts.load()[fact].union(datasets))))


@when(parsers.parse('a fact file "{name}" reads "{text}"'))
def fact_file(ctx, name: str, text: str) -> None:
    ctx.attempt(lambda: facts.parse(name, text.replace("\\n", "\n")))
