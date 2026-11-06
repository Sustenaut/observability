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
