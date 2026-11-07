"""The trends page: plain HTML from the server, with no script and nothing loaded from
elsewhere. It sits behind oauth2-proxy and the team sign-in (k8s/page.yaml), which
let in only people holding the observability role; it shows what it reads and acts
on nothing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from observability.page.queries import WINDOWS, Sender, Trends

BASE = "/trends/integrations"
STYLE = ("body{font:15px/1.5 system-ui;margin:2rem auto;max-width:72rem;padding:0 1rem;color-scheme:light dark}"
         "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem}th,td{padding:.25rem .5rem;"
         "border-bottom:1px solid #8884;text-align:left}td.n,th.n{text-align:right}.bad{font-weight:600}"
         "h2{margin-top:2rem}")
HEADERS = {"Cache-Control": "private, no-store",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f'<!doctype html><html lang="en"><meta charset="utf-8">'
                        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>'
                        f"<style>{STYLE}</style><h1>{escape(title)}</h1>{body}</html>", headers=HEADERS)


def _when(moment: datetime | None) -> str:
    return "never" if moment is None else moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ms(value: Any) -> str:
    return "" if value is None else f"{int(value):,}"


def _table(head: list[str], rows: list[list[str]], numeric: set[int], empty: str) -> str:
    if not rows:
        return f"<p>{escape(empty)}</p>"
    th = "".join(f"<th{' class=n' if i in numeric else ''}>{escape(h)}" for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(cell if cell.startswith("<td") else f"<td{' class=n' if i in numeric else ''}>{cell}"
                                    for i, cell in enumerate(row)) for row in rows)
    return f"<table><tr>{th}</tr>{body}</table>"


def _plugins(trends: Trends) -> str:
    rows = []
    for r in trends.plugins:
        rate = 100 * r["error_count"] / r["call_count"] if r["call_count"] else 0.0
        mark = " class='n bad'" if r["error_count"] else " class=n"
        rows.append([escape(r["project"]), escape(r["app"]), escape(r["plugin"]), escape(r["operation"]),
                     f"{r['call_count']:,}", f"<td{mark}>{r['error_count']:,} ({rate:.1f}%)",
                     f"{r['refused_count']:,}", f"{r['unavailable_count']:,}", _ms(r["typical_ms"]),
                     _ms(r["slowest_ms"])])
    return _table(["Project", "App", "Plugin", "Operation", "Calls", "Errors", "Refused", "Unavailable",
                   "Typical ms", "Slowest ms"], rows, {4, 5, 6, 7, 8, 9}, "No calls in the last day.")


def _sender_state(s: Sender) -> str:
    if s.silent:
        return "<td class=bad>silent"
    if s.expected == "on-demand":
        return "<td>on demand"
    return "<td>reporting"


def _senders(trends: Trends) -> str:
    rows = [[escape(s.project), escape(s.kind), escape(s.prefix), escape(s.expected or "not configured"),
             escape(_when(s.last_seen)), str(s.windows_last_hour), _sender_state(s)] for s in trends.senders]
    return _table(["Project", "Kind", "Sender", "Expected", "Last report", "Windows, last hour", "State"], rows,
                  {5}, "No sender has reported in the last day.")


def _page_times(trends: Trends) -> str:
    if not trends.page_times:
        return "<p>No sender answered requests in the last day.</p>"
    parts = []
    for (project, prefix), windows in sorted(trends.page_times.items()):
        rows = [[escape(_when(w["bucket"])), f"{w['page_count']:,}", _ms(w["page_ms_low"]),
                 _ms(w["page_ms_median"]) + (" ≈" if w["page_ms_median_approximate"] else ""),
                 _ms(w["page_ms_high"]), "<td class=bad>cold start" if w["cold_start"] else "<td>"] for w in windows]
        parts.append(f"<h3>{escape(project)} / {escape(prefix)}</h3>" + _table(
            ["Window", "Requests", "Quickest ms", "Median ms", "Slowest ms", ""], rows, {1, 2, 3, 4}, ""))
    return f"<p>The newest {WINDOWS} two-minute windows of each sender that answered requests.</p>" + "".join(parts)


def _evidence(value: Any) -> str:
    found = json.loads(value) if isinstance(value, str) else (value or {})
    return escape(", ".join(f"{k}: {v}" for k, v in sorted(found.items())))


def _signals(trends: Trends) -> str:
    opened = [[escape(r["severity"]) if r["severity"] != "critical" else f"<td class=bad>{escape(r['severity'])}",
               escape(r["rule_id"]), escape(r["subject"]), escape(_when(r["started_at"])), _evidence(r["evidence"])]
              for r in trends.open_signals]
    recent = [[escape(r["severity"]), escape(r["rule_id"]), escape(r["subject"]), escape(_when(r["started_at"])),
               escape(_when(r["ended_at"]))] for r in trends.recent_signals]
    return ("<h3>Open</h3>" + _table(["Severity", "Rule", "Subject", "Since", "Evidence"], opened, set(), "None open.")
            + "<h3>Ended in the last day</h3>"
            + _table(["Severity", "Rule", "Subject", "Started", "Ended"], recent, set(), "None ended in the last day."))


def render(trends: Trends) -> HTMLResponse:
    return _page("Integrations: trends", (
        f"<p>As of {escape(_when(trends.now))}, over the last day.</p>"
        "<h2>Signals</h2>" + _signals(trends)
        + "<h2>Calls by plugin</h2>" + _plugins(trends)
        + "<h2>Senders</h2>" + _senders(trends)
        + "<h2>Page times</h2>" + _page_times(trends)))


def create_app(load: Callable[[], Trends]) -> FastAPI:
    """`load` reads the trends now; it raises when BigQuery doesn't answer."""
    app = FastAPI(title="Observability", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(f"{BASE}/")

    @app.get(BASE, include_in_schema=False)
    def to_the_page() -> RedirectResponse:
        return RedirectResponse(f"{BASE}/")

    @app.get(f"{BASE}/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        try:
            trends = load()
        except Exception:  # noqa: BLE001 - whatever stopped it, the page says to try again
            raise HTTPException(503, "BigQuery didn't answer: try again") from None
        return render(trends)

    return app
