"""What the page's pod runs: observability.page.main:app."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from observability import config, senders
from observability.page.app import create_app
from observability.page.queries import signal, trends


def build():  # pragma: no cover - the pod's wiring, with its real credential
    from integrations.calls import Caller

    from observability.bigquery import Warehouse
    from observability.cli import CREDENTIAL, credential

    datasets = config.datasets(os.environ[config.VARIABLE])
    expected = senders.parse(os.environ.get(senders.VARIABLE, ""), datasets)
    warehouse = Warehouse(Caller("Sustenaut/observability", "page"), credential(os.environ[CREDENTIAL]))
    from observability import rules

    every = rules.load()
    return create_app(
        lambda: trends(warehouse.query, datasets, expected, datetime.now(timezone.utc)),
        lambda rule_id, subject, started: signal(warehouse.query, datasets, every, rule_id, subject, started,
                                                 datetime.now(timezone.utc)))


app = build() if os.environ.get("OBSERVABILITY_GOOGLE_CREDENTIAL_FILE") else None
