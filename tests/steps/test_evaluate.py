"""Steps running `observability evaluate` in-process, its BigQuery a stand-in
transport that answers Google's token endpoint and BigQuery's REST API, and
runs each query on fixture rows (local_bigquery.py). Storage is a stand-in in
the same transport: its listing follows what was written, which pubtest's fake
services do not do. What the run printed, its exit code and stderr are
pubtest's result; the Thens here read the signals it printed."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from integrations.calls import Response
from pytest_bdd import given, parsers, scenarios, then, when

from observability import bigquery, cli, store
from observability.evaluate import Signal

from .local_bigquery import DAY, Warehouse

ROOT = Path(__file__).resolve().parents[2]

scenarios("../features/evaluate.feature")

TOKEN_URI = "https://oauth2.example.test/token"
STORAGE = "https://storage.example.test"
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
        self.storage = Storage()

    def answer(self, sql: str) -> dict:
        columns, rows = self.warehouse.typed(sql)
        fields = [{"name": n, "type": duckdb_type(t)} for n, t in columns]
        return {"schema": {"fields": fields}, "jobComplete": True,
                "rows": [{"f": [{"v": cell(f["type"], v)} for f, v in zip(fields, row)]} for row in rows]}

    def send(self, request, timeout: float) -> Response:
        if request.url.startswith(STORAGE):
            return self.storage.send(request)
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


class Storage:
    """The signals tenant: a buffer's put, get and list."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.refuse_writes = self.refuse_lists = False
        self.vanish: set[str] = set()

    def send(self, request) -> Response:
        assert request.headers["Authorization"] == "Bearer storage-token"
        path = request.url.removeprefix(f"{STORAGE}/signals/")
        if path.startswith("list?"):
            if self.refuse_lists:
                return Response(503, b'{"error": "down"}')
            assert "prefix=inbox%2Fsignals%2F" in path
            names = sorted(self.files)
            for name in self.vanish:
                self.files.pop(name, None)
            return Response(200, json.dumps({"files": [{"name": n, "size": 1, "uploaded": "2026-11-01T10:00:00Z"}
                                                       for n in names], "cursor": None}).encode())
        if request.method == "PUT":
            if self.refuse_writes:
                return Response(500, b'{"error": "full"}')
            self.files[path] = request.body
            return Response(200, json.dumps({"name": path, "size": len(request.body)}).encode())
        if path not in self.files:
            return Response(404, b'{"error": "no such file"}')
        return Response(200, self.files[path])


@pytest.fixture
def warehouse() -> Warehouse:
    return Warehouse()


@pytest.fixture
def google(warehouse: Warehouse) -> Google:
    warehouse.signals([])
    return Google(warehouse)


@given(parsers.parse('the dataset "{dataset}" holds "{fixture}"'))
def holds(warehouse: Warehouse, dataset: str, fixture: str) -> None:
    warehouse.load(dataset, fixture)


def made_key() -> dict:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return {"project_id": "example-project", "client_email": "reader@example-project.iam.gserviceaccount.com",
            "private_key": pem, "token_uri": TOKEN_URI}


@given(parsers.parse('a service account key in "{path}", the credential file'))
def a_key(ctx, monkeypatch, path: str) -> None:
    file = ctx.directory / path
    file.write_text(json.dumps(made_key()), encoding="utf-8")
    monkeypatch.setenv("OBSERVABILITY_GOOGLE_CREDENTIAL_FILE", str(file))


@given(parsers.parse('a file "{path}" holding the credential of "{configmap}"'))
def configmap_credential(ctx, path: str, configmap: str) -> None:
    data = yaml.safe_load((ROOT / configmap).read_text(encoding="utf-8"))["data"]
    (ctx.directory / path).write_text(data["credential.json"], encoding="utf-8")


@when("the evaluator's warehouse is made from the credential file")
def warehouse_made(ctx) -> None:
    from integrations.calls import Caller

    from observability.bigquery import Warehouse
    from observability.cli import credential

    def made() -> dict:
        made = Warehouse(Caller("Sustenaut/observability", "evaluator"),
                         credential(os.environ["OBSERVABILITY_GOOGLE_CREDENTIAL_FILE"]))
        return {"token": type(made.token).__name__, "project": made.project}

    ctx.attempt(made)


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


def evaluate(ctx, google: Google, argv: list[str]) -> None:
    """`observability evaluate`, in-process: its exit code as the program's."""
    ctx.attempt(lambda: sys.exit(cli.main(argv, transport=google, storage_token="storage-token")))


@when(parsers.parse("the evaluator runs at {clock}"))
def runs_at(ctx, google: Google, clock: str) -> None:
    evaluate(ctx, google, ["evaluate", "--now", f"{DAY}T{clock}:00"])


@when("the evaluator runs now")
def runs_now(ctx, google: Google) -> None:
    evaluate(ctx, google, ["evaluate"])


def printed(ctx) -> list[dict]:
    """The signals the run printed, one JSON line each."""
    return [json.loads(line) for line in ctx.outcome.stdout.splitlines() if line.strip()]


def find(ctx, rule: str, subject: str) -> dict:
    found = [s for s in printed(ctx) if s["rule_id"] == rule and s["subject"] == subject]
    assert len(found) == 1, printed(ctx)
    return found[0]


@then(parsers.re(r'it starts "(?P<rule>[a-z_]+)" for "(?P<subject>[^"]+)"(?: as (?P<severity>[a-z]+))?'
                 r'(?: with "(?P<key>[a-z_]+)" "(?P<value>[^"]+)")?$'))
def starts(ctx, rule: str, subject: str, severity: str | None, key: str | None, value: str | None) -> None:
    signal = find(ctx, rule, subject)
    assert signal["ended_at"] is None
    if severity:
        assert signal["severity"] == severity
    if key:
        assert json.loads(signal["evidence"])[key] == value, signal["evidence"]


@then(parsers.parse("every signal started at {clock} and has not ended"))
def all_started(ctx, clock: str) -> None:
    signals = printed(ctx)
    assert signals
    assert all(s["started_at"] == f"{DAY}T{clock}:00Z" and s["ended_at"] is None for s in signals), signals


@then(parsers.parse('it writes nothing for "{rule}" on "{subject}"'))
def nothing_for_rule(ctx, rule: str, subject: str) -> None:
    signals = printed(ctx)
    assert not [s for s in signals if (s["rule_id"], s["subject"]) == (rule, subject)], signals


@then(parsers.re(r'it writes nothing for "(?P<what>[^"]+)"$'))
def nothing_for(ctx, what: str) -> None:
    signals = printed(ctx)
    assert not [s for s in signals if what in (s["rule_id"], s["subject"])], signals


@then(parsers.parse('it ends "{rule}" for "{subject}", started at {clock}'))
def ends(ctx, rule: str, subject: str, clock: str) -> None:
    signal = find(ctx, rule, subject)
    assert signal["started_at"] == f"{DAY}T{clock}:00Z"
    assert signal["ended_at"] == signal["emitted_at"] == f"{DAY}T10:30:00Z"
    ctx.ended = signal


@then(parsers.parse('its evidence says "{key}" "{value}"'))
def evidence_says(ctx, key: str, value: str) -> None:
    assert json.loads(ctx.ended["evidence"])[key] == value


@when("BigQuery answers a row of every type")
def every_type(ctx) -> None:
    fields = [{"name": "n", "type": "INT64"}, {"name": "x", "type": "FLOAT64"}, {"name": "b", "type": "BOOL"},
              {"name": "t", "type": "TIMESTAMP"}, {"name": "s", "type": "STRING"},
              {"name": "l", "type": "INTEGER", "mode": "REPEATED"}, {"name": "z", "type": "STRING"}]
    answer = {"schema": {"fields": fields}, "rows": [{"f": [
        {"v": "3"}, {"v": "0.5"}, {"v": "true"}, {"v": "1762000000.0"}, {"v": "a"},
        {"v": [{"v": "1"}, {"v": "2"}]}, {"v": None}]}]}
    ctx.attempt(lambda: bigquery.rows(answer))


def moment(clock: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{clock}:00").replace(tzinfo=timezone.utc)


@given(parsers.parse('the tenant holds a start of "{rule}" for "{subject}" at {clock}, not loaded yet'))
def pending_start(google: Google, rule: str, subject: str, clock: str) -> None:
    signal = Signal(rule, "1", subject, "critical", moment(clock), None, {"was": 1}, moment(clock))
    data = store.encode([signal])
    google.storage.files[store.place(moment(clock), data)] = data


@given(parsers.parse('the tenant holds an end of "{rule}" for "{subject}" started at {start}, not loaded yet'))
def pending_end(google: Google, rule: str, subject: str, start: str) -> None:
    signal = Signal(rule, "1", subject, "warning", moment(start), moment("10:28"), {}, moment("10:28"))
    data = store.encode([signal])
    google.storage.files[store.place(moment("10:28"), data)] = data


@given("a file in the tenant is loaded between its listing and its reading")
def vanishing(google: Google) -> None:
    signal = Signal("drops", "1", "example/gone", "warning", moment("10:20"), None, {}, moment("10:20"))
    data = store.encode([signal])
    name = store.place(moment("10:20"), data)
    google.storage.files[name] = data
    google.storage.vanish.add(name)


@given("storage refuses writes")
def refuse_writes(google: Google) -> None:
    google.storage.refuse_writes = True


@given("storage does not answer listings")
def refuse_lists(google: Google) -> None:
    google.storage.refuse_lists = True


@then(parsers.parse("one file of {count:d} signals is written to {folder}"))
def written(ctx, google: Google, count: int, folder: str) -> None:
    files = {n: d for n, d in google.storage.files.items() if n.startswith(folder)}
    assert len(files) == 1, google.storage.files
    name, data = next(iter(files.items()))
    assert name.startswith(f"{folder}103000-evaluator-") and name.endswith(".avro"), name
    assert [s.record() for s in store.decode(data)] == printed(ctx)
    assert len(printed(ctx)) == count
    assert f"wrote {count} signals to signals/{name}" in ctx.outcome.stderr


@then("nothing is written to the tenant")
def nothing_written(google: Google) -> None:
    assert not [n for n in google.storage.files if "103000" in n], google.storage.files


@when("the pods' Google credentials are read")
def pods_credentials(ctx) -> None:
    """A mismatch fails only at run time, as Google's STS refusing the token:
    each pod's projected token, its audience, and where it is mounted."""

    def pods() -> list[dict]:
        found = []
        for name, path in (("evaluator", ["spec", "jobTemplate", "spec", "template", "spec"]),
                           ("page", ["spec", "template", "spec"])):
            spec = next(d for d in yaml.safe_load_all((ROOT / "k8s" / f"{name}.yaml").read_text(encoding="utf-8"))
                        if d and d["kind"] in ("CronJob", "Deployment"))
            for key in path:
                spec = spec[key]
            (volume,) = [v for v in spec["volumes"] if v["name"] == "google-token"]
            (source,) = volume["projected"]["sources"]
            mounts = {m["name"]: m["mountPath"] for m in spec["containers"][0]["volumeMounts"]}
            env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
            found.append({"pod": name, "account": spec["serviceAccountName"],
                          "automount": spec["automountServiceAccountToken"],
                          "audience": source["serviceAccountToken"]["audience"],
                          "token": f"{mounts['google-token']}/{source['serviceAccountToken']['path']}",
                          "credential_dir": mounts["google-credential"],
                          "credential": env["OBSERVABILITY_GOOGLE_CREDENTIAL_FILE"]})
        return found

    ctx.attempt(pods)


@when(parsers.parse('the credential in "{configmap}" is read'))
def configmap_read(ctx, configmap: str) -> None:
    ctx.attempt(lambda: json.loads(yaml.safe_load((ROOT / configmap).read_text(encoding="utf-8"))
                                   ["data"]["credential.json"]))
