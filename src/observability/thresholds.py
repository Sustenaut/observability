"""Thresholds other than the rules' own, and severities, as configuration.

Configuration, never in this repository: OBSERVABILITY_THRESHOLDS is YAML (or
JSON), a versioned block that gives some rules' params another number, and
may give a rule another severity:

    version: 1
    rules:
      ingest_silent:
        silent_minutes: 20
      storage_unreachable:
        failed_cycles: 4
        severity: warning

A rule or param it leaves out keeps the rule file's default; empty or unset,
every rule runs as its file says. It names only rules there are and params
they have, each a number, and a severity is critical, warning or info:
anything else is refused, and the evaluator doesn't start.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from observability.rules import SEVERITIES, Rule, is_number

VARIABLE = "OBSERVABILITY_THRESHOLDS"
VERSIONS = (1,)
KEYS = {"version", "rules"}


def parse(text: str, every: dict[str, Rule]) -> dict[str, dict[str, Any]]:
    """Each rule's overrides, checked against the rules there are: its params'
    numbers, and `severity` when it has one."""
    import yaml  # noqa: PLC0415 - only the evaluator and the page need it

    try:
        data = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as error:
        raise ValueError(f"{VARIABLE} is not YAML: {error}") from None
    if data is None:
        return {}
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError(f"{VARIABLE} is a mapping with a version and its rules")
    unknown = sorted(str(k) for k in set(data) - KEYS)
    if unknown:
        raise ValueError(f"{VARIABLE} has a version and rules, and no {', '.join(unknown)}")
    if data["version"] not in VERSIONS or isinstance(data["version"], bool):
        raise ValueError(f"{VARIABLE} is version {', '.join(map(str, VERSIONS))}, not {data['version']}")
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
            elif not is_number(value):
                raise ValueError(f"{VARIABLE}: {rule_id}'s {key} is a number, not {value}")
        out[str(rule_id)] = dict(given)
    return out


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
