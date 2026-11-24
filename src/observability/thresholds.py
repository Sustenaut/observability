"""Thresholds other than the rules' own, severities, and the senders' tiers, as configuration.

Configuration, never in this repository: OBSERVABILITY_THRESHOLDS is YAML (or
JSON), a versioned block that gives some rules' params another number, may
give a rule another severity, and may set a tier's numbers:

    version: 2
    tiers:
      idle:
        silent_minutes: 600
    rules:
      ingest_silent:
        margin_minutes: 10
      storage_unreachable:
        failed_cycles: 4
        severity: warning

A rule or param it leaves out keeps the rule file's default; empty or unset,
every rule runs as its file says. It names only rules there are and params
they have, each a finite number above 0, and a severity is critical, warning or info:
anything else is refused, and the evaluator doesn't start.

A tier is how a sender reports (observability.senders): `deadline_seconds`,
how long a call waits before its file goes, `heartbeat_seconds`, how often a
sender with no calls still reports, and `silent_minutes`, how long a sender
may go unseen before sender_silent says so. The senders read the first two as
CALL_LOG_DEADLINE_SECONDS and CALL_LOG_HEARTBEAT_SECONDS (integrations'
StorageSink); here they are only checked, and the owner's state repository
holds each repository's to the tier its senders have. A tier's silence is at
least a heartbeat and five minutes, so a sender that reports on time is never
called silent. A tier or number it leaves out keeps TIERS'.

Version 1 had no tiers. It is read as version 2 by the chained transformers
(TRANSFORMS, upgrade): sender_silent's silent_minutes becomes the tight and
cycle tiers' silent_minutes, and ingest_silent's silent_minutes becomes its
margin_minutes past them. `observability thresholds --upgrade` prints a block
at the latest version, for the state repository to keep.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from observability.rules import SEVERITIES, Rule, is_threshold

VARIABLE = "OBSERVABILITY_THRESHOLDS"
VERSIONS = (1, 2)
LATEST = VERSIONS[-1]
KEYS = {1: {"version", "rules"}, 2: {"version", "tiers", "rules"}}
# The tiers and their numbers when the block gives none.
TIERS: dict[str, dict[str, float]] = {
    "tight": {"deadline_seconds": 30, "heartbeat_seconds": 300, "silent_minutes": 10},
    "idle": {"deadline_seconds": 28800, "heartbeat_seconds": 28800, "silent_minutes": 540},
    "cycle": {"deadline_seconds": 120, "heartbeat_seconds": 120, "silent_minutes": 10},
}
TIER_KEYS = ("deadline_seconds", "heartbeat_seconds", "silent_minutes")
# Past a heartbeat, the time a sender's file takes to reach BigQuery, at most.
LOAD_MINUTES = 5


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Version 1 to 2: the silences sender_silent and ingest_silent had as params
    move to the tiers, and to ingest_silent's margin past them."""
    found = data.get("rules")
    rules = {k: dict(v) if isinstance(v, dict) else v for k, v in found.items()} if isinstance(found, dict) else found
    tiers: dict[str, dict[str, Any]] = {}
    if isinstance(rules, dict):
        sender = rules.get("sender_silent")
        if isinstance(sender, dict) and "silent_minutes" in sender:
            minutes = sender.pop("silent_minutes")
            tiers = {"tight": {"silent_minutes": minutes}, "cycle": {"silent_minutes": minutes}}
            if not sender:
                del rules["sender_silent"]
        ingest = rules.get("ingest_silent")
        if isinstance(ingest, dict) and "silent_minutes" in ingest:
            minutes = ingest.pop("silent_minutes")
            base = tiers.get("cycle", TIERS["cycle"])["silent_minutes"]
            ingest["margin_minutes"] = max(minutes - base, 1) if is_threshold(minutes) and is_threshold(base) else minutes
    out: dict[str, Any] = {"version": 2}
    if tiers:
        out["tiers"] = tiers
    if found is not None:
        out["rules"] = rules
    return out


# Each version's step to the next; a block chains them up to LATEST.
TRANSFORMS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _v1_to_v2}


def _shape(data: Any) -> None:
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError(f"{VARIABLE} is a mapping with a version and its rules")
    if data["version"] not in VERSIONS or isinstance(data["version"], bool):
        raise ValueError(f"{VARIABLE} is version {', '.join(map(str, VERSIONS))}, not {data['version']}")
    unknown = sorted(str(k) for k in set(data) - KEYS[data["version"]])
    if unknown:
        allowed = " and ".join(sorted(KEYS[data["version"]] - {"version"}))
        raise ValueError(f"{VARIABLE} version {data['version']} has a version and {allowed}, and no {', '.join(unknown)}")


def upgrade(data: dict[str, Any]) -> dict[str, Any]:
    """A block at the latest version, through each version's transformer in turn."""
    _shape(data)
    while data["version"] < LATEST:
        data = TRANSFORMS[data["version"]](data)
        _shape(data)
    return data


def _read(text: str) -> dict[str, Any] | None:
    """The block, at the latest version; None when it is empty."""
    import yaml  # noqa: PLC0415 - only the evaluator and the page need it

    try:
        data = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as error:
        raise ValueError(f"{VARIABLE} is not YAML: {error}") from None
    return None if data is None else upgrade(data)


def _tiers(data: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    found = (data or {}).get("tiers") or {}
    if not isinstance(found, dict):
        raise ValueError(f"{VARIABLE}: tiers maps each tier to its numbers")
    out = {name: dict(numbers) for name, numbers in TIERS.items()}
    for name, given in found.items():
        if name not in TIERS:
            raise ValueError(f"{VARIABLE}: the tiers are {', '.join(TIERS)}, not {name}")
        if not isinstance(given, dict):
            raise ValueError(f"{VARIABLE}: the tier {name} maps each of {', '.join(TIER_KEYS)} to a number")
        for key, value in given.items():
            if key not in TIER_KEYS:
                raise ValueError(f"{VARIABLE}: the tier {name} has {', '.join(TIER_KEYS)}, not {key}")
            if not is_threshold(value):
                raise ValueError(f"{VARIABLE}: the tier {name}'s {key} is a finite number above 0, not {value}")
            out[name][key] = value
    for name, numbers in out.items():
        if numbers["silent_minutes"] < numbers["heartbeat_seconds"] / 60 + LOAD_MINUTES:
            raise ValueError(f"{VARIABLE}: the tier {name}'s silent_minutes is at least its heartbeat and "
                             f"{LOAD_MINUTES} minutes ({numbers['heartbeat_seconds'] / 60 + LOAD_MINUTES:g}), "
                             f"not {numbers['silent_minutes']:g}, or every sender of it would be called silent")
    return out


def tiers(text: str) -> dict[str, dict[str, float]]:
    """Each tier's numbers, as OBSERVABILITY_THRESHOLDS's text sets them over TIERS'."""
    return _tiers(_read(text))


def parse(text: str, every: dict[str, Rule]) -> dict[str, dict[str, Any]]:
    """Each rule's overrides, checked against the rules there are: its params'
    numbers, and `severity` when it has one. The tiers are checked too."""
    data = _read(text)
    if data is None:
        return {}
    _tiers(data)
    found = data.get("rules") or {}
    if not isinstance(found, dict):
        raise ValueError(f"{VARIABLE}: rules maps each rule to its thresholds")
    out: dict[str, dict[str, Any]] = {}
    for rule_id, given in found.items():
        rule = every.get(rule_id)
        if rule is None:
            raise ValueError(f"{VARIABLE} names the rule {rule_id}, which there is not")
        if not isinstance(given, dict):
            raise ValueError(f"{VARIABLE}: {rule_id} maps each of its params to a number")
        for key, value in given.items():
            if key == "severity":
                if value not in SEVERITIES:
                    raise ValueError(f"{VARIABLE}: {rule_id}'s severity is {', '.join(SEVERITIES)}, not {value}")
            elif key not in rule.params:
                has = f"its params are {', '.join(sorted(rule.params))}" if rule.params else "it has no params"
                raise ValueError(f"{VARIABLE}: {rule_id} has no param {key}; {has}")
            elif not is_threshold(value):
                raise ValueError(f"{VARIABLE}: {rule_id}'s {key} is a finite number above 0, not {value}")
        out[str(rule_id)] = dict(given)
    return out


def upgraded(text: str) -> dict[str, Any]:
    """The block as the latest version writes it: what `thresholds --upgrade` prints."""
    return _read(text) or {"version": LATEST, "rules": {}}


def apply(every: dict[str, Rule], overrides: dict[str, dict[str, Any]]) -> dict[str, Rule]:
    """The rules as they run: each with its effective params, its defaults updated
    by the overrides, and its severity."""
    out = {}
    for rule_id, rule in every.items():
        given = dict(overrides.get(rule_id, {}))
        severity = given.pop("severity", rule.severity)
        out[rule_id] = replace(rule, params={**rule.params, **given}, severity=severity)
    return out


def effective(text: str, every: dict[str, Rule]) -> dict[str, Rule]:
    """The rules as OBSERVABILITY_THRESHOLDS's text says they run."""
    return apply(every, parse(text, every))
