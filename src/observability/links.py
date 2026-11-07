"""Where a signal's own page is: the one address everything that names a signal
links to, such as a notifier's message. It needs nothing installed, so another
repository can depend on this package for it alone.

A signal is known by its rule, its subject and when it started, which together
never change, whether it is open or has ended:

    /signals/<rule_id>/<started>/<subject>

`started` is its `started_at` in UTC as `YYYYMMDDTHHMMSSZ`, with `.ffffff`
before the Z when it has microseconds. `subject` comes last, percent-encoded
except for `/`, so a subject such as `example/app` reads as it is.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

SITE = "https://observability.sustenaut.eu"
PREFIX = "/signals"
STARTED = re.compile(r"^(\d{8}T\d{6})(?:\.(\d{6}))?Z$")
RULE_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def started_key(started_at: datetime) -> str:
    """`started_at` as the address writes it."""
    moment = (started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    fraction = f".{moment.microsecond:06d}" if moment.microsecond else ""
    return moment.strftime("%Y%m%dT%H%M%S") + fraction + "Z"


def parse_started(text: str) -> datetime | None:
    """The moment an address's `started` names, or None when it isn't one."""
    if not (match := STARTED.match(text)):
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.replace(microsecond=int(match.group(2) or 0))


def signal_path(rule_id: str, subject: str, started_at: datetime) -> str:
    """The path of a signal's page."""
    if not RULE_ID.match(rule_id):
        raise ValueError(f"not a rule id: {rule_id!r}")
    return f"{PREFIX}/{rule_id}/{started_key(started_at)}/{quote(subject, safe='/')}"


def signal_url(rule_id: str, subject: str, started_at: datetime, site: str = SITE) -> str:
    """The address of a signal's page, on `site`."""
    return site.rstrip("/") + signal_path(rule_id, subject, started_at)
