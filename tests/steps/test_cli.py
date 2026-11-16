"""Steps driving `bin/observability` as a user would, from OBSERVABILITY_BIN_DIR."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/cli.feature")


@pytest.fixture
def result() -> dict:
    return {"env": {k: v for k, v in os.environ.items() if k != "OBSERVABILITY_DATASETS"}}


@given(parsers.parse('OBSERVABILITY_DATASETS is "{value}"'))
def datasets_variable(result: dict, value: str) -> None:
    result["env"]["OBSERVABILITY_DATASETS"] = value


@when("I run observability with no arguments")
def run_bare(result: dict) -> None:
    run(result, "")


@when(parsers.parse('I run observability with "{args}"'))
def run(result: dict, args: str) -> None:
    program = Path(os.environ["OBSERVABILITY_BIN_DIR"]) / "observability"
    result["done"] = subprocess.run([str(program), *shlex.split(args)],
                                    capture_output=True, text=True, check=False, env=result["env"])


@then("it succeeds")
def succeeds(result: dict) -> None:
    assert result["done"].returncode == 0, result["done"].stderr


@then(parsers.parse('it prints "{text}"'))
def prints(result: dict, text: str) -> None:
    text = text.replace("\\t", "\t")
    assert text in result["done"].stdout, result["done"].stdout


@then(parsers.parse('it fails with "{message}"'))
def fails(result: dict, message: str) -> None:
    assert result["done"].returncode == 2, result["done"].stdout
    assert f"observability: {message}" in result["done"].stderr, result["done"].stderr


@then("the image the package and the tests install one integrations wheel")
def the_image_the_package_and_the_tests_install_one_integrations_wheel():
    """integrations is pinned in three places, and CI builds no image: the Dockerfile's lock
    (evaluator-requirements.in and .lock), pyproject.toml's extra and tests/requirements.txt
    must name one wheel, or the deploy's build is the first to find out."""
    import re

    root = Path(__file__).resolve().parents[2]
    wheel = re.compile(r"https://github\.com/Sustenaut/integrations/releases/download/\S+?\.whl")
    found = {name: set(wheel.findall((root / name).read_text(encoding="utf-8")))
             for name in ("pyproject.toml", "tests/requirements.txt", "evaluator-requirements.in",
                          "evaluator-requirements.lock")}
    assert all(len(urls) == 1 for urls in found.values()), found
    assert len(set().union(*found.values())) == 1, found
