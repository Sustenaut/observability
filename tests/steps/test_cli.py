"""`bin/observability` runs through pubtest's `I run`, from OBSERVABILITY_BIN_DIR;
here are only the Whens that read where the integrations wheel is pinned."""

from __future__ import annotations

import re
from pathlib import Path

from pytest_bdd import scenarios, when

scenarios("../features/cli.feature")

ROOT = Path(__file__).resolve().parents[2]
PINNED_IN = ("evaluator-requirements.in", "evaluator-requirements.lock", "pyproject.toml", "tests/requirements.txt")
WHEEL = re.compile(r"https://github\.com/Sustenaut/integrations/releases/download/\S+?\.whl")


def wheels(name: str) -> set[str]:
    return set(WHEEL.findall((ROOT / name).read_text(encoding="utf-8")))


@when("the integrations wheels the requirements name are read")
def counted(ctx) -> None:
    ctx.attempt(lambda: [{"file": name, "wheels": len(wheels(name))} for name in PINNED_IN])


@when("the integrations wheels the requirements name are gathered")
def gathered(ctx) -> None:
    ctx.attempt(lambda: sorted(set().union(*(wheels(name) for name in PINNED_IN))))
