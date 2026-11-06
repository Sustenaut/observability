"""Which call log datasets observability reads.

They are configuration, never in this repository: OBSERVABILITY_DATASETS
lists them, comma-separated, where observability runs (a repository
variable in CI, the pod's environment in production). A dataset named
`calls_<project>` is that project's; any other name is its own project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VARIABLE = "OBSERVABILITY_DATASETS"
# A BigQuery dataset's name: letters, digits and underscores.
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,1023}")


@dataclass(frozen=True)
class Dataset:
    """One project's call log dataset."""

    name: str

    @property
    def project(self) -> str:
        return self.name.removeprefix("calls_")


def datasets(listed: str) -> list[Dataset]:
    """The datasets a comma-separated list names, each checked."""
    names = [name.strip() for name in listed.split(",") if name.strip()]
    for name in names:
        if not NAME.fullmatch(name):
            raise ValueError(f"{name!r} is not a BigQuery dataset name")
    return [Dataset(name) for name in names]
