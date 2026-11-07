"""What the page's pod runs: observability.page.main:app."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from observability import config, senders
from observability.page.app import create_app
from observability.page.queries import trends


def build():  # pragma: no cover - the pod's wiring, with real keys
    from integrations.calls import Caller

    from observability.bigquery import Warehouse
    from observability.cli import KEY, key

    datasets = config.datasets(os.environ[config.VARIABLE])
    expected = senders.parse(os.environ.get(senders.VARIABLE, ""), datasets)
    warehouse = Warehouse(Caller("Sustenaut/observability", "page"), key(os.environ[KEY]))
    return create_app(lambda: trends(warehouse.query, datasets, expected, datetime.now(timezone.utc)))


app = build() if os.environ.get("OBSERVABILITY_BIGQUERY_KEY") else None
