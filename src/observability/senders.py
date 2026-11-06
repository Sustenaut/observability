"""Which senders each project should have, and how often they report.

Configuration, never in this repository: OBSERVABILITY_SENDERS is YAML (or
JSON) mapping each project to its sender prefixes, each `always` (it
reports every two minutes, so silence is a fault) or `on-demand` (it runs
only when asked, as a Cloud Run service scaled to zero does):

    example:
      app: always
      plan: on-demand
"""

from __future__ import annotations

from observability.config import Dataset

VARIABLE = "OBSERVABILITY_SENDERS"
KINDS = ("always", "on-demand")


def parse(text: str, datasets: list[Dataset]) -> dict[str, dict[str, str]]:
    """The senders, each checked, for projects among the datasets'."""
    import yaml  # noqa: PLC0415 - only the evaluator needs it

    try:
        data = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as error:
        raise ValueError(f"{VARIABLE} is not YAML: {error}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{VARIABLE} maps each project to its senders")
    projects = {d.project for d in datasets}
    for project, senders in data.items():
        if project not in projects:
            raise ValueError(f"{VARIABLE} names {project}, which no dataset is")
        if not isinstance(senders, dict) or not senders:
            raise ValueError(f"{VARIABLE}: {project} maps each sender prefix to always or on-demand")
        for prefix, kind in senders.items():
            if kind not in KINDS:
                raise ValueError(f"{VARIABLE}: {project}/{prefix} is always or on-demand, not {kind}")
    return {str(p): {str(s): k for s, k in senders.items()} for p, senders in data.items()}


def always(senders: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """The (project, prefix) pairs expected to report all the time."""
    return sorted((p, s) for p, prefixes in senders.items() for s, kind in prefixes.items() if kind == "always")
