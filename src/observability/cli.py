"""The `observability` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from observability import __version__, config, facts, senders, thresholds

# The variable that names Google's credential file (its path, never a value).
GOOGLE_FILE = "OBSERVABILITY_GOOGLE_CREDENTIAL_FILE"
# With it set, the evaluator writes its signals to storage's signals tenant, and
# reads back those not loaded yet; without it, it only prints them.
STORAGE = "OBSERVABILITY_STORAGE_URL"
TENANT = "signals"
# The pod's projected service-account token for storage, always here: no path
# to it is taken from outside.
TOKEN_FILE = "/var/run/secrets/storage.sustenaut.eu/token"


def main(argv: list[str] | None = None, *, transport: Any = None, storage_token: Any = None) -> int:
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
    checking = commands.add_parser(
        "thresholds", help=f"check ${thresholds.VARIABLE} against the rules")
    checking.add_argument("--check", action="store_true", required=True,
                          help="check only: exit 2 with the reason when it would be refused")
    args = parser.parse_args(argv)
    if args.command == "thresholds":
        return check_thresholds()
    if args.command == "rules":
        from observability import rules  # noqa: PLC0415 - needs PyYAML

        for rule in rules.load().values():
            print(f"{rule.id}\tversion {rule.version}\t{rule.severity}\t{rule.summary}")
        return 0
    if args.command == "evaluate":
        try:
            return evaluate(args.now, transport, storage_token)
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
        if not datasets and not fact.fixed:
            raise ValueError(f"no dataset: give --dataset or set {config.VARIABLE}")
    except KeyError:
        print(f"observability: no fact {args.fact}; there are {', '.join(known)}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"observability: {error}", file=sys.stderr)
        return 2
    print(fact.union(datasets))
    return 0


def check_thresholds() -> int:
    """Whether OBSERVABILITY_THRESHOLDS is one the evaluator would start with: 0 when
    it is, 2 with the reason when it isn't."""
    from observability import rules  # noqa: PLC0415 - needs PyYAML

    text = os.environ.get(thresholds.VARIABLE, "")
    try:
        found = thresholds.parse(text, rules.load())
    except ValueError as error:
        print(f"observability: {error}", file=sys.stderr)
        return 2
    print(f"{thresholds.VARIABLE}: overrides for {', '.join(found)}" if found
          else f"{thresholds.VARIABLE}: no overrides, every rule as its file says")
    return 0


def credential(path: str) -> dict:
    """Google's credential for BigQuery, from the file at `path`: an external_account
    credential (Workload Identity, google-credential.yaml) or a service account's key."""
    if not path:
        raise ValueError(f"no credential: set {GOOGLE_FILE}")
    try:
        found = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{GOOGLE_FILE} is not a readable JSON file") from None
    if isinstance(found, dict) and (found.get("type") == "external_account" or
                                    {"project_id", "client_email", "private_key", "token_uri"} <= set(found)):
        return found
    raise ValueError(f"{GOOGLE_FILE} is neither an external_account credential nor a service account's key")


def evaluate(when: str | None, transport: Any, storage_token: Any = None) -> int:
    from integrations.calls import Caller, IntegrationError  # noqa: PLC0415 - the evaluator's dependencies

    from integrations.clients.storage import Storage  # noqa: PLC0415

    from observability import evaluate as evaluator, rules, store  # noqa: PLC0415
    from observability.bigquery import Warehouse  # noqa: PLC0415

    now = datetime.fromisoformat(when) if when else datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    datasets = config.datasets(os.environ.get(config.VARIABLE, ""))
    if not datasets:
        raise ValueError(f"no dataset: set {config.VARIABLE}")
    expected = senders.parse(os.environ.get(senders.VARIABLE, ""), datasets)
    every = thresholds.effective(os.environ.get(thresholds.VARIABLE, ""), rules.load())
    caller = Caller("Sustenaut/observability", "evaluator", transport=transport)
    warehouse = Warehouse(caller, credential(os.environ.get(GOOGLE_FILE, "")))
    url = os.environ.get(STORAGE, "")
    signals = store.Store(Storage(caller, TENANT, base_url=url, token=storage_token,
                                  token_file=None if storage_token else Path(TOKEN_FILE))) if url else None
    try:
        # Storage first: a file loaded between the two is then in both, never in neither.
        pending = signals.pending() if signals else []
        opened = store.still_open(evaluator.open_signals(
            warehouse.query(evaluator.OPEN_SIGNALS.replace("{{now}}", facts.timestamp(now)))), pending)
    except IntegrationError as error:
        # Without them every breach would start again, so nothing is evaluated.
        raise ValueError(f"could not read the open signals: {error}") from None
    outcome = evaluator.evaluate(list(every.values()), warehouse.query, datasets, senders.always(expected),
                                 opened, now)
    for signal in outcome.signals:
        print(json.dumps(signal.record(), sort_keys=True))
    for rule, error in sorted(outcome.failed.items()):
        print(f"observability: {rule} failed, so its signals stay as they were: {error}", file=sys.stderr)
    unwritten = False
    if signals:
        try:
            where = signals.write(outcome.signals, now)
        except IntegrationError as error:
            # They are worked out again next run, as nothing records them as open.
            print(f"observability: the signals could not be written: {error}", file=sys.stderr)
            unwritten = True
        else:
            if where:
                print(f"observability: wrote {len(outcome.signals)} signals to {TENANT}/{where}", file=sys.stderr)
    return 1 if outcome.failed or unwritten else 0
