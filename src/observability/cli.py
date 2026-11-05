"""The `observability` command."""

from __future__ import annotations

import argparse

from observability import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="observability",
        description="Trends across Sustenaut's services. It reads, derives signals and reports; it never acts.",
    )
    parser.add_argument("--version", action="version", version=f"observability {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
