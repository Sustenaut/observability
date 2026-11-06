"""The `observability` command."""

from __future__ import annotations

import argparse
import os
import sys

from observability import __version__, config, facts


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
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
