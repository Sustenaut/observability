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

from observability import links
from observability.page.queries import WINDOWS, Sender, SignalView, Trends

BASE = "/trends/integrations"
STYLE = ("body{font:15px/1.5 system-ui;margin:2rem auto;max-width:72rem;padding:0 1rem;color-scheme:light dark}"
         "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem}th,td{padding:.25rem .5rem;"
         "border-bottom:1px solid #8884;text-align:left}td.n,th.n{text-align:right}.bad{font-weight:600}"
         "h2{margin-top:2rem}pre{white-space:pre-wrap;font-size:13px}svg{max-width:100%;height:auto}"
         "dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem}dt{font-weight:600}")
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


def _link(r: dict[str, Any]) -> str:
    """The signal's subject, linking to its own page."""
    path = links.signal_path(r["rule_id"], r["subject"], _utc(r["started_at"]))
    return f'<a href="{escape(path)}">{escape(r["subject"])}</a>'


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _signals(trends: Trends) -> str:
    opened = [[escape(r["severity"]) if r["severity"] != "critical" else f"<td class=bad>{escape(r['severity'])}",
               escape(r["rule_id"]), _link(r), escape(_when(r["started_at"])), _evidence(r["evidence"])]
              for r in trends.open_signals]
    recent = [[escape(r["severity"]), escape(r["rule_id"]), _link(r), escape(_when(r["started_at"])),
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


def _clock(moment: datetime) -> str:
    return _utc(moment).astimezone(timezone.utc).strftime("%H:%M")


def _chart(view: SignalView) -> str:
    """The rule's trend over the window, against its threshold, as an inline SVG: no
    script and nothing loaded. The signal's span is shaded."""
    trend = view.rule.trend
    if trend is None:
        return "<p>This rule has no trend to chart yet.</p>"
    points = [(r["bucket"], float(r["value"])) for r in view.trend if r["value"] is not None]
    if not points:
        return f"<p>No {escape(trend.label.lower())} in this window.</p>"
    width, height, pad = 720, 220, 36
    start, span = view.since.timestamp(), max(1.0, (view.until - view.since).total_seconds())
    top = max([trend.threshold, *(v for _, v in points)]) * 1.1 or 1.0

    def x(moment: datetime) -> float:
        return pad + (width - 2 * pad) * (_utc(moment).timestamp() - start) / span

    def y(value: float) -> float:
        return height - pad - (height - 2 * pad) * value / top

    began, ended = x(view.signal["started_at"]), x(view.signal.get("ended_at") or view.until)
    line = " ".join(f"{x(at):.1f},{y(v):.1f}" for at, v in points)
    dots = "".join(f'<circle cx="{x(at):.1f}" cy="{y(v):.1f}" r="2.5" fill="currentColor"/>' for at, v in points)
    limit = y(trend.threshold)
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(trend.label)}">'
            f'<rect x="{began:.1f}" y="{pad}" width="{max(1.0, ended - began):.1f}" height="{height - 2 * pad}" '
            f'fill="#d33" fill-opacity=".12"/>'
            f'<line x1="{pad}" x2="{width - pad}" y1="{limit:.1f}" y2="{limit:.1f}" stroke="#d33" '
            f'stroke-dasharray="4 4"/>'
            f'<text x="{width - pad}" y="{limit - 4:.1f}" text-anchor="end" font-size="11" fill="#d33">'
            f'threshold {trend.threshold:g}</text>'
            f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.5"/>{dots}'
            f'<text x="{pad}" y="{height - 10}" font-size="11" fill="currentColor">{_clock(view.since)}</text>'
            f'<text x="{width - pad}" y="{height - 10}" font-size="11" text-anchor="end" fill="currentColor">'
            f'{_clock(view.until)}</text>'
            f'<text x="{pad}" y="{pad - 10}" font-size="11" fill="currentColor">{escape(trend.label)}, '
            f'up to {top / 1.1:g}</text></svg>')


CONTEXT = {
    "sender": ("Windows of the sender", ["bucket", "reports", "calls", "drops", "storage_failures", "page_count",
                                         "page_ms_median", "page_ms_high", "cold_start"]),
    "ingest": ("Windows of the ingest pod", ["bucket", "waiting_files", "waiting_oldest_seconds", "rejected_files",
                                             "problems"]),
    "plugin": ("Calls from the app to the plugin", ["bucket", "operation", "calls", "errors", "refused", "unavailable",
                                                  "latency_ms_median", "latency_ms_max"]),
}


TEXT_COLUMNS = {"bucket", "operation", "cold_start", "problems"}


def _cell(value: Any) -> str:
    if isinstance(value, datetime):
        return escape(_when(value))
    if isinstance(value, bool):
        return "yes" if value else ""
    return "" if value is None else escape(str(value))


def _context(view: SignalView) -> str:
    if not view.context:
        return ""
    title, columns = CONTEXT[view.context]
    rows = [[_cell(r.get(c)) for c in columns] for r in view.rows]
    numeric = {i for i, c in enumerate(columns) if c not in TEXT_COLUMNS}
    return f"<h2>{escape(title)}</h2>" + _table([c.replace("_", " ") for c in columns], rows, numeric,
                                                 "None in this window.")


def _history(view: SignalView) -> str:
    rows = []
    for r in view.history:
        this = _utc(r["started_at"]) == _utc(view.signal["started_at"])
        rows.append([escape(r["severity"]), _link(r) if not this else "<td>this one",
                     escape(_when(r["started_at"])), escape(_when(r.get("ended_at")) if r.get("ended_at") else "open")])
    return _table(["Severity", "Subject", "Started", "Ended"], rows, set(), "No others in the last 30 days.")


def render_signal(view: SignalView) -> HTMLResponse:
    s, rule = view.signal, view.rule
    ended = s.get("ended_at")
    lasted = _utc(ended or view.now) - _utc(s["started_at"])
    state = (f"ended {escape(_when(ended))}, after {int(lasted.total_seconds() // 60)} min" if ended
             else f"<span class=bad>open</span> for {int(lasted.total_seconds() // 60)} min")
    facts = "".join(f"<dt>{escape(k)}<dd>{escape(str(v))}" for k, v in sorted(view.evidence.items()))
    return _page(f"{s['rule_id']}: {s['subject']}", (
        f"<p>As of {escape(_when(view.now))}. <a href=\"/trends/integrations/\">All trends</a>.</p>"
        f"<dl><dt>Rule<dd>{escape(s['rule_id'])}, version {escape(str(s['rule_version']))}"
        f"<dt>Severity<dd>{escape(s['severity'])}<dt>Subject<dd>{escape(s['subject'])}"
        f"<dt>Started<dd>{escape(_when(s['started_at']))}<dt>State<dd>{state}</dl>"
        f"<p>{escape(rule.summary)}</p>"
        f"<h2>Evidence</h2><dl>{facts}</dl>"
        f"<h2>Trend</h2><p>From {escape(_when(view.since))} to {escape(_when(view.until))}; the signal's span is "
        f"shaded.</p>{_chart(view)}"
        + _context(view)
        + f"<h2>This rule's signals for {escape(s['subject'])}</h2>{_history(view)}"
        f"<h2>The rule</h2><p>Looks back {rule.lookback_minutes} minutes.</p><pre>{escape(rule.query)}</pre>"))


def create_app(load: Callable[[], Trends],
               load_signal: Callable[[str, str, datetime], SignalView | None] | None = None) -> FastAPI:
    """`load` reads the trends now, and `load_signal` one signal's page (rule id, subject,
    start); each raises when BigQuery doesn't answer."""
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

    @app.get(f"{links.PREFIX}/{{rule_id}}/{{started}}/{{subject:path}}", response_class=HTMLResponse)
    def signal_page(rule_id: str, started: str, subject: str) -> HTMLResponse:
        moment = links.parse_started(started)
        if load_signal is None or moment is None or not links.RULE_ID.match(rule_id):
            raise HTTPException(404, "No such signal")
        try:
            view = load_signal(rule_id, subject, moment)
        except Exception:  # noqa: BLE001 - whatever stopped it, the page says to try again
            raise HTTPException(503, "BigQuery didn't answer: try again") from None
        if view is None:
            raise HTTPException(404, "No such signal")
        return render_signal(view)

    return app
