"""Steps running `observability evaluate` in-process, its BigQuery a stand-in
transport that answers Google's token endpoint and BigQuery's REST API, and
runs each query on fixture rows (local_bigquery.py)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from integrations.calls import Response
from pytest_bdd import given, parsers, scenarios, then, when

from observability import bigquery, cli

from .local_bigquery import DAY, Warehouse

scenarios("../features/evaluate.feature")

TOKEN_URI = "https://oauth2.example.test/token"
QUERIES = "https://bigquery.googleapis.com/bigquery/v2/projects/example-project/queries"


def duckdb_type(name: str) -> str:
    if name in ("BIGINT", "INTEGER", "HUGEINT"):
        return "INTEGER"
    if name in ("DOUBLE", "FLOAT") or name.startswith("DECIMAL"):
        return "FLOAT"
    if name == "BOOLEAN":
        return "BOOLEAN"
    if name.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    return "STRING"


def cell(kind: str, value: object) -> object:
    if value is None:
        return None
    if kind == "TIMESTAMP":
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return str(moment.timestamp())
    if kind == "BOOLEAN":
        return "true" if value else "false"
    return str(value)


class Google:
    """Google's token endpoint and BigQuery's queries, on fixture rows."""

    def __init__(self, warehouse: Warehouse):
        self.warehouse = warehouse
        self.refuse: str | None = None
        self.second_ask = self.never = self.paged = False
        self.pending: dict[str, dict] = {}

    def answer(self, sql: str) -> dict:
        columns, rows = self.warehouse.typed(sql)
        fields = [{"name": n, "type": duckdb_type(t)} for n, t in columns]
        return {"schema": {"fields": fields}, "jobComplete": True,
                "rows": [{"f": [{"v": cell(f["type"], v)} for f, v in zip(fields, row)]} for row in rows]}

    def send(self, request, timeout: float) -> Response:
        if request.url == TOKEN_URI:
            return Response(200, json.dumps({"access_token": "ya29.test"}).encode())
        assert request.headers["Authorization"] == "Bearer ya29.test"
        if request.method == "POST":
            sql = json.loads(request.body)["query"]
            if self.refuse and f".{self.refuse}" in sql:
                return Response(400, json.dumps({"error": {"message": "Not found: Table"}}).encode())
            job = f"job{len(self.pending)}"
            answer = {**self.answer(sql), "jobReference": {"jobId": job}}
            if self.second_ask or self.never:
                self.pending[job] = answer
                return Response(200, json.dumps({"jobComplete": False, "jobReference": {"jobId": job}}).encode())
            return Response(200, json.dumps(self.page(job, answer, 0)).encode())
        job = request.url.split("/queries/")[1].split("?")[0]
        if self.never:
            return Response(200, json.dumps({"jobComplete": False, "jobReference": {"jobId": job}}).encode())
        start = int(request.url.split("pageToken=")[1]) if "pageToken=" in request.url else 0
        return Response(200, json.dumps(self.page(job, self.pending.get(job) or self.paged_answers[job], start)).encode())

    def page(self, job: str, answer: dict, start: int) -> dict:
        if not self.paged:
            return answer
        self.__dict__.setdefault("paged_answers", {})[job] = answer
        rows = answer.get("rows", [])
        out = {**answer, "rows": rows[start:start + 1]}
        if start + 1 < len(rows):
            out["pageToken"] = str(start + 1)
        else:
            out.pop("pageToken", None)
        return out


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def google(warehouse: Warehouse) -> Google:
    warehouse.signals([])
    return Google(warehouse)


@pytest.fixture
def run(monkeypatch) -> dict:
    for name in ("OBSERVABILITY_DATASETS", "OBSERVABILITY_SENDERS", "OBSERVABILITY_BIGQUERY_KEY"):
        monkeypatch.delenv(name, raising=False)
    return {}


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, run: dict, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)


@given(parsers.re(r'(?P<name>OBSERVABILITY_[A-Z_]+) is "(?P<value>.*)"$'))
def setting(monkeypatch, run: dict, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)


def made_key() -> dict:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return {"project_id": "example-project", "client_email": "reader@example-project.iam.gserviceaccount.com",
            "private_key": pem, "token_uri": TOKEN_URI}


@given("a service account key in OBSERVABILITY_BIGQUERY_KEY")
def a_key(monkeypatch, run: dict) -> None:
    run["key"] = made_key()
    monkeypatch.setenv("OBSERVABILITY_BIGQUERY_KEY", json.dumps(run["key"]))


@given("the service account key is in base64")
def key_base64(monkeypatch, run: dict) -> None:
    monkeypatch.setenv("OBSERVABILITY_BIGQUERY_KEY", base64.b64encode(json.dumps(run["key"]).encode()).decode())


@given(parsers.parse('the open signal "{rule}" for "{subject}" since {clock}'))
def open_signal(warehouse: Warehouse, google: Google, rule: str, subject: str, clock: str) -> None:
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{clock}:00", "evidence": {"was": 1}}])


@given(parsers.parse('the signal "{rule}" for "{subject}" from {start} to {end}'))
def closed_signal(warehouse: Warehouse, google: Google, rule: str, subject: str, start: str, end: str) -> None:
    warehouse.signals([{"rule_id": rule, "subject": subject, "started_at": f"{start}:00"},
                       {"rule_id": rule, "subject": subject, "started_at": f"{start}:00", "ended_at": f"{end}:00"}])


@given(parsers.parse('BigQuery refuses queries of "{table}"'))
def refuses(google: Google, table: str) -> None:
    google.refuse = table


@given("BigQuery answers each query only on the second ask")
def second_ask(google: Google) -> None:
    google.second_ask = True


@given("BigQuery never finishes a query")
def never(google: Google) -> None:
    google.never = True


@given("BigQuery answers one row a page")
def paged(google: Google) -> None:
    google.paged = True


def evaluate(run: dict, google: Google, capsys, argv: list[str]) -> None:
    run["code"] = cli.main(argv, transport=google)
    captured = capsys.readouterr()
    run["out"], run["err"] = captured.out, captured.err
    run["signals"] = [json.loads(line) for line in captured.out.splitlines() if line.strip()]


@when(parsers.parse("the evaluator runs at {clock}"))
def runs_at(run: dict, google: Google, capsys, clock: str) -> None:
    evaluate(run, google, capsys, ["evaluate", "--now", f"{DAY}T{clock}:00"])


@when("the evaluator runs now")
def runs_now(run: dict, google: Google, capsys) -> None:
    evaluate(run, google, capsys, ["evaluate"])


@then("it succeeds")
def succeeds(run: dict) -> None:
    assert run["code"] == 0, run["err"]


@then(parsers.parse("it fails with code {code:d}"))
def fails(run: dict, code: int) -> None:
    assert run["code"] == code, run["out"] + run["err"]


@then(parsers.parse('stderr mentions "{text}"'))
def stderr_mentions(run: dict, text: str) -> None:
    assert text in run["err"], run["err"]


def find(run: dict, rule: str, subject: str) -> dict:
    found = [s for s in run["signals"] if s["rule_id"] == rule and s["subject"] == subject]
    assert len(found) == 1, run["signals"]
    return found[0]


@then(parsers.re(r'it starts "(?P<rule>[a-z_]+)" for "(?P<subject>[^"]+)"(?: as (?P<severity>[a-z]+))?'
                 r'(?: with "(?P<key>[a-z_]+)" "(?P<value>[^"]+)")?$'))
def starts(run: dict, rule: str, subject: str, severity: str | None, key: str | None, value: str | None) -> None:
    signal = find(run, rule, subject)
    assert signal["ended_at"] is None
    if severity:
        assert signal["severity"] == severity
    if key:
        assert json.loads(signal["evidence"])[key] == value, signal["evidence"]


@then(parsers.parse("every signal started at {clock} and has not ended"))
def all_started(run: dict, clock: str) -> None:
    assert run["signals"]
    assert all(s["started_at"] == f"{DAY}T{clock}:00Z" and s["ended_at"] is None for s in run["signals"])


@then(parsers.parse('it writes nothing for "{what}"'))
def nothing_for(run: dict, what: str) -> None:
    assert not [s for s in run["signals"] if what in (s["rule_id"], s["subject"])], run["signals"]


@then(parsers.parse('it ends "{rule}" for "{subject}", started at {clock}'))
def ends(run: dict, rule: str, subject: str, clock: str) -> None:
    signal = find(run, rule, subject)
    assert signal["started_at"] == f"{DAY}T{clock}:00Z"
    assert signal["ended_at"] == signal["emitted_at"] == f"{DAY}T10:30:00Z"
    run["last"] = signal


@then(parsers.parse('its evidence says "{key}" "{value}"'))
def evidence_says(run: dict, key: str, value: str) -> None:
    assert json.loads(run["last"]["evidence"])[key] == value


@when("BigQuery answers a row of every type")
def every_type(run: dict) -> None:
    fields = [{"name": "n", "type": "INT64"}, {"name": "x", "type": "FLOAT64"}, {"name": "b", "type": "BOOL"},
              {"name": "t", "type": "TIMESTAMP"}, {"name": "s", "type": "STRING"},
              {"name": "l", "type": "INTEGER", "mode": "REPEATED"}, {"name": "z", "type": "STRING"}]
    answer = {"schema": {"fields": fields}, "rows": [{"f": [
        {"v": "3"}, {"v": "0.5"}, {"v": "true"}, {"v": "1762000000.0"}, {"v": "a"},
        {"v": [{"v": "1"}, {"v": "2"}]}, {"v": None}]}]}
    run["rows"] = bigquery.rows(answer)


@then("the row reads as Python values")
def python_values(run: dict) -> None:
    assert run["rows"] == [{"n": 3, "x": 0.5, "b": True, "t": datetime.fromtimestamp(1762000000, tz=timezone.utc),
                            "s": "a", "l": [1, 2], "z": None}]
