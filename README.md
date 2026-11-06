# observability

Trends across Sustenaut's services, behind the team sign-in.

Each service logs its calls to outside services (see
[integrations](https://github.com/Sustenaut/integrations)). Observability reads
those logs, turns them into signals with versioned rules, and shows the trends.
It gathers and reports; it never acts on what it finds. Acting on a signal is
another service's job.

This repository is code only. Which services and datasets it reads is
configuration, given where it runs, so nothing here names them.

## Facts

A fact is what the call log says, before any rule judges it: one versioned
BigQuery query under `src/observability/facts/`, whose header names it and
gives its version. The version goes up whenever a change could change a row,
and every row carries `fact` and `fact_version`, so each signal can be traced
to the query it came from.

| Fact | Reads | One row per |
|---|---|---|
| `sender_windows` | `status` | kind, sender prefix and two-minute bucket |
| `call_rollups` | `calls` | scope, app, plugin, operation and two-minute bucket |

- **`sender_windows`** names a sender by its prefix, the pod or Cloud Run
  revision name without its generated suffix, since that suffix changes with
  each pod and revision. Rows of one bucket are merged: counts summed, the
  quickest and slowest answers kept, the median a count-weighted mean of the
  rows' medians (`page_ms_median_approximate` when more than one row
  answered), the largest buffer and any cold start. Ingest rows keep their own
  fields: what waits, what was rejected and loaded, the day's load jobs,
  whether storage answered, and the problems. A bucket with no row is a
  sender's silence; the fact records only what was reported.
- **`call_rollups`** counts each app's calls, its errors by outcome
  (`refused`, `unavailable`) and retries, with the median and slowest latency.
  Its `scope` is `plugin` for calls to outside services and `request_total`
  for the `service-total` and `client-total` operations, which time a whole
  request: a rule about plugins reads only `scope = 'plugin'`.

Which datasets are read is configuration: `OBSERVABILITY_DATASETS` lists them,
comma-separated, and a dataset `calls_<project>` is that project's.

```sh
bin/observability facts                                 # each fact and its version
bin/observability facts sender_windows --dataset calls_example
```

prints the query, for every dataset given, as one `UNION ALL`. The suite runs
each fact on fixture rows in DuckDB, its SQL put in DuckDB's dialect by
sqlglot, so CI needs no BigQuery; `tests/schemas/` holds the call log's
columns.
## Uptime

`.github/workflows/uptime.yml` probes each site every five minutes from
GitHub Actions, off the server it watches, so it still reports when that
server is down. Every other part of observability reads what services
report; this is the one check that doesn't depend on them.

- **Targets** are the repository variable `UPTIME_TARGETS`, a JSON list of
  `{"name", "url", "expect_status", "channel"}`. `expect_status` defaults
  to 200. `channel`, a channel's or a person's id, says where that target's
  alerts go; without it they go to the default, `UPTIME_SLACK_CHANNEL`. A
  redirect is compared, not followed, so a site behind sign-in can be
  probed by the redirect it answers with. No target is named here, and
  with the variable unset the workflow does nothing.
- **Down** means two runs in a row failed: no answer within 10 s, or a
  status other than the one expected, each run trying a failing target
  twice. The state between runs, each target's failures in a row, is a
  small file, `uptime-state.json` in the working directory, kept in
  the Actions cache. If the cache is lost, the next run starts afresh.
- **Alerts:** going down and recovering are posted by the Sustenaut Slack
  bot (`SUSTENAUT_SLACK_BOT_TOKEN`, `chat.postMessage`), one post per
  channel: each target's own, or the default `UPTIME_SLACK_CHANNEL`. Slack answers 200 even to a post it refuses, so the probe reads
  its `ok` and fails the run with Slack's reason. Every other Slack post
  goes through the integrations service, but that service runs on the
  server being watched, so this one is made directly, as release-state's
  failure notice is. Without the token nothing is posted, and without the default nothing is
  posted for the targets that have no channel of their own.
  A run fails while any target is down, so GitHub's failed-run email is
  the backup.

```sh
UPTIME_TARGETS='[{"name": "example", "url": "https://example.test/healthz"}]' \
  PYTHONPATH=src python3 -m observability.uptime
```

**Setting it up.** The bot's token, the channel and the targets live in
Bitwarden's Sustenaut project, as `slack-bot-token`, `uptime-slack-channel`
and `uptime-targets`. `pubkit.json`'s `secrets` list sends them here, as
the secret `SUSTENAUT_SLACK_BOT_TOKEN` and the variables
`UPTIME_SLACK_CHANNEL` and `UPTIME_TARGETS`. The bot must be in each
channel it posts to; a direct message needs nothing more.

```sh
./with-secrets ./pubkit app-secrets --check   # names and lengths only; sends nothing
./with-secrets ./pubkit app-secrets
```

To change the targets, edit `uptime-targets` in Bitwarden and run it again.

GitHub turns off a public repository's scheduled workflows after 60 days
without activity in it. If it does, re-enable the workflow from the
Actions tab.

## Signals

A signal is one rule's finding about one subject over a span of time:

| Field | Meaning |
|---|---|
| `rule_id`, `rule_version` | The rule that found it, and which version of it |
| `subject` | What it is about |
| `severity` | How much it matters |
| `started_at`, `ended_at` | When it began, and ended (empty while it lasts) |
| `evidence` | The facts the rule found it from |
| `emitted_at` | When it was written |

A rule's version changes whenever what it finds could change, so every
signal can be traced to the exact rule that produced it.

A signal is written twice: when it starts, with `ended_at` empty, and when
it ends, with the same `started_at`. A breach that lasts is written once,
not on every run.

## Rules

A rule is one YAML file under `src/observability/rules/`: its `id`,
`version`, `severity` (`critical`, `warning` or `info`), a one-line
`summary`, `lookback_minutes`, and a BigQuery `query` over the facts. The
query returns one row per subject in breach now; `subject` names it, and
every other column is the signal's evidence. It reads `{{fact:<id>}}` (every
dataset's rows, from its lookback on), and may use `{{now}}`,
`{{projects}}` and `{{always_senders}}`.

| Rule | Severity | Finds |
|---|---|---|
| `sender_silent` | critical | an always-on sender with no report for more than 6 minutes |
| `ingest_silent` | critical | a project the ingest pod has reported nothing for in more than 6 minutes |
| `storage_unreachable` | critical | storage not answering the ingest pod's latest cycle |
| `storage_failures` | warning | a sender failing to write to storage in the last 6 minutes |
| `drops` | warning | a sender dropping call records in the last 6 minutes |
| `inbox_stale` | warning | a file waiting more than 10 minutes in a project's inbox |
| `rejected_files` | warning | files in a project's buffer that couldn't load |
| `load_jobs_near_limit` | warning | more than 1,200 of the 1,400 load jobs a table used today |
| `plugin_errors` | warning | more than 5% of an app's calls to a plugin failing over 30 minutes, out of at least 20 |
| `slow_pages` | warning | a warm sender answering slower than 5 seconds in the last 6 minutes |
| `cold_start_share` | info | the share of a sender's answering windows in the last day that began cold |

**Senders** are configuration: `OBSERVABILITY_SENDERS` maps each project to
its sender prefixes, each `always` (silence is a fault) or `on-demand` (it
runs only when asked, as a Cloud Run service scaled to zero does). Only
`always` senders can be silent.

```yaml
example:
  app: always
  plan: on-demand
```

## The evaluator

`observability evaluate` runs every rule against BigQuery and prints the
signals that start and end now, one JSON line each, in the shape of
`observability.signals`. It reads the signals still open from that table,
so an open signal isn't written again. A rule whose query fails ends none
of its signals, because not knowing isn't all clear, and the run then exits
1. Its settings:

| Variable | What |
|---|---|
| `OBSERVABILITY_DATASETS` | the call log datasets to read |
| `OBSERVABILITY_SENDERS` | the senders each project should have (above) |
| `OBSERVABILITY_BIGQUERY_KEY` | `observability-reader`'s key: its JSON, or that JSON in base64 |
| `OBSERVABILITY_STORAGE_URL` | storage's address, to write the signals there (optional) |

It needs the `evaluator` extra (`pip install '.[evaluator]'`): PyYAML, and
the integrations library, whose `Caller` makes each BigQuery and storage
call with its class's timeout and retries, and fastavro.

With `OBSERVABILITY_STORAGE_URL` set, each run also writes its signals as one
Avro file to storage's `signals` tenant, under `inbox/signals/<date>/`, with
the pod's projected token from `/var/run/secrets/storage.sustenaut.eu/token`.
The integrations ingest pod loads that inbox into `observability.signals` and
deletes what it loaded. Until a file is loaded, the evaluator reads it back:
the open signals are those in the table, with the starts and ends still in
the inbox laid over them. It reads the inbox before the table, so a file
loaded in between is seen twice, never missed. Without the variable it only
prints.

## Working on it

```sh
make venv        # .venv from the hash-locked test requirements
make check       # everything CI runs
```

Releases are cut with pubrel: record each code change with
`pubrel add <category> "<change>"`, and a release is `pubrel prepare` and
its pull request.

## Licence

Apache-2.0.
