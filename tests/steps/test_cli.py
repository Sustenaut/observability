"""Steps driving `bin/observability` as a user would, from OBSERVABILITY_BIN_DIR."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest
from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/cli.feature")


@pytest.fixture
def result() -> dict:
    return {}


@when("I run observability with no arguments")
def run_bare(result: dict) -> None:
    run(result, "")


@when(parsers.parse('I run observability with "{args}"'))
def run(result: dict, args: str) -> None:
    program = Path(os.environ["OBSERVABILITY_BIN_DIR"]) / "observability"
    result["done"] = subprocess.run([str(program), *shlex.split(args)],
                                    capture_output=True, text=True, check=False)


@then("it succeeds")
def succeeds(result: dict) -> None:
    assert result["done"].returncode == 0, result["done"].stderr


@then(parsers.parse('it prints "{text}"'))
def prints(result: dict, text: str) -> None:
    assert text in result["done"].stdout, result["done"].stdout
