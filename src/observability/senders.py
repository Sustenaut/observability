"""Which senders each project should have, and how often they report.

Configuration, never in this repository: OBSERVABILITY_SENDERS is YAML (or
JSON) mapping each project to its sender prefixes, each with how it reports:

    example:
      app: tight
      worker: idle
      plan: on-demand

- `tight`: it writes a file once a call has waited a short deadline, and a
  report alone every heartbeat (minutes) when it has no calls;
- `idle`: the same with a deadline and heartbeat of hours, for a sender whose
  calls can wait;
- `cycle`: a file every two minutes, calls or not, as every sender once did;
- `always`: the name `cycle` had, which still means it;
- `on-demand`: it runs only when asked, as a Cloud Run service scaled to zero
  does, so its silence is no fault.

A tier's numbers (its deadline, heartbeat and how long its silence may last)
are OBSERVABILITY_THRESHOLDS' (observability.thresholds). A sender of any
tier but on-demand is expected: sender_silent says so once it has gone unseen
for its tier's silent_minutes.
"""

from __future__ import annotations

from observability.config import Dataset

VARIABLE = "OBSERVABILITY_SENDERS"
TIERS = ("tight", "idle", "cycle")
# A kind that names a tier by another name.
ALIASES = {"always": "cycle"}
KINDS = (*TIERS, *ALIASES, "on-demand")


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
    kinds = ", ".join(KINDS[:-1]) + f" or {KINDS[-1]}"
    for project, senders in data.items():
        if project not in projects:
            raise ValueError(f"{VARIABLE} names {project}, which no dataset is")
        if not isinstance(senders, dict) or not senders:
            raise ValueError(f"{VARIABLE}: {project} maps each sender prefix to {kinds}")
        for prefix, kind in senders.items():
            if kind not in KINDS:
                raise ValueError(f"{VARIABLE}: {project}/{prefix} is {kinds}, not {kind}")
    return {str(p): {str(s): k for s, k in senders.items()} for p, senders in data.items()}


def tier(kind: str) -> str | None:
    """The tier a kind names; None for on-demand, which has none."""
    return ALIASES.get(kind, kind) if kind != "on-demand" else None


def always(senders: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """The (project, prefix) pairs expected to report all the time: every tier's."""
    return sorted((p, s) for p, prefixes in senders.items() for s, kind in prefixes.items() if tier(kind))


def expected(senders: dict[str, dict[str, str]], tiers: dict[str, dict[str, float]]) -> list[tuple[str, str, str, float]]:
    """Each expected sender: its project, prefix, tier, and how long it may go unseen."""
    return sorted((p, s, tier(kind), tiers[tier(kind)]["silent_minutes"])
                  for p, prefixes in senders.items() for s, kind in prefixes.items() if tier(kind))


def windows(senders: dict[str, dict[str, str]], tiers: dict[str, dict[str, float]],
            datasets: list[Dataset]) -> list[tuple[str, float]]:
    """How long each project may go without the ingest pod's report: its quickest
    expected sender's silence. The pod reports on a project when its files come,
    and at every sweep, so a project with no expected sender has the longest."""
    longest = max(numbers["silent_minutes"] for numbers in tiers.values())
    found = {d.project: longest for d in datasets}
    for project, _, _, minutes in expected(senders, tiers):
        found[project] = min(found.get(project, longest), minutes)
    return sorted(found.items())
