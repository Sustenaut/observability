"""The `observability` command."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from observability import __version__, config, facts, senders

KEY = "OBSERVABILITY_BIGQUERY_KEY"


def main(argv: list[str] | None = None, *, transport: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="observability",
        description="Trends across Sustenaut's services. It reads, derives signals and reports; it never acts.",
    )
    parser.add_argument("--version", action="version", version=f"observability {__version__}")
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("facts", help="list the facts, or print one's query")
    listing.add_argument("fact", nargs="?", help="the fact whose query to print")
    listing.add_argument("--dataset", action="append", default=[],
                         help=f"a call log dataset to read; repeat it (default: ${config.VARIABLE})")
    commands.add_parser("rules", help="list the rules, with their versions and severities")
    evaluating = commands.add_parser(
        "evaluate", help="run every rule, and print the signals starting and ending now as JSON lines")
    evaluating.add_argument("--now", help="the moment to evaluate, in ISO 8601 (default: now)")
    args = parser.parse_args(argv)
    if args.command == "rules":
        from observability import rules  # noqa: PLC0415 - needs PyYAML

        for rule in rules.load().values():
            print(f"{rule.id}\tversion {rule.version}\t{rule.severity}\t{rule.summary}")
        return 0
    if args.command == "evaluate":
        try:
            return evaluate(args.now, transport)
        except ValueError as error:
            print(f"observability: {error}", file=sys.stderr)
            return 2
    if args.command != "facts":
        parser.print_help()
        return 0
    known = facts.load()
    if args.fact is None:
        for fact in known.values():
            print(f"{fact.id}\tversion {fact.version}\treads {fact.reads}")
        return 0
    try:
        fact = known[args.fact]
        listed = ",".join(args.dataset) if args.dataset else os.environ.get(config.VARIABLE, "")
        datasets = config.datasets(listed)
        if not datasets:
            raise ValueError(f"no dataset: give --dataset or set {config.VARIABLE}")
    except KeyError:
        print(f"observability: no fact {args.fact}; there are {', '.join(known)}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"observability: {error}", file=sys.stderr)
        return 2
    print(fact.union(datasets))
    return 0


def key(text: str) -> dict:
    """A service account's key: its JSON, or that JSON in base64, as Bitwarden keeps it."""
    for attempt in (text, None):
        try:
            found = json.loads(attempt if attempt is not None else base64.b64decode(text, validate=True))
        except (ValueError, binascii.Error):
            continue
        if isinstance(found, dict) and {"project_id", "client_email", "private_key", "token_uri"} <= set(found):
            return found
    raise ValueError(f"{KEY} is not a service account's key")


def evaluate(when: str | None, transport: Any) -> int:
    from integrations.calls import Caller, IntegrationError  # noqa: PLC0415 - the evaluator's dependencies

    from observability import evaluate as evaluator, rules  # noqa: PLC0415
    from observability.bigquery import Warehouse  # noqa: PLC0415

    now = datetime.fromisoformat(when) if when else datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    datasets = config.datasets(os.environ.get(config.VARIABLE, ""))
    if not datasets:
        raise ValueError(f"no dataset: set {config.VARIABLE}")
    expected = senders.parse(os.environ.get(senders.VARIABLE, ""), datasets)
    warehouse = Warehouse(Caller("Sustenaut/observability", "evaluator", transport=transport),
                          key(os.environ.get(KEY, "")))
    try:
        opened = evaluator.open_signals(
            warehouse.query(evaluator.OPEN_SIGNALS.replace("{{now}}", facts.timestamp(now))))
    except IntegrationError as error:
        # Without them every breach would start again, so nothing is evaluated.
        raise ValueError(f"could not read the open signals: {error}") from None
    outcome = evaluator.evaluate(list(rules.load().values()), warehouse.query, datasets, senders.always(expected),
                                 opened, now)
    for signal in outcome.signals:
        print(json.dumps(signal.record(), sort_keys=True))
    for rule, error in sorted(outcome.failed.items()):
        print(f"observability: {rule} failed, so its signals stay as they were: {error}", file=sys.stderr)
    return 1 if outcome.failed else 0
