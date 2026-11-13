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
| `need_states` | `convergence.need_states` | deploy service need and walk |
| `pubkit_checks` | `platform.pubkit_checks` | repository, check and night |

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
- **`need_states`** is what the convergence engine found of each deploy
  service's needs in each walk, from the one table `convergence.need_states`
  (the integrations ingest pod loads it from storage's `need-states` buffer),
  not a project's call log: a fact whose `reads` is `dataset.table` reads that
  table once, whatever the call log datasets.
- **`pubkit_checks`** is how each repository on the release board stood against
  pubkit, night by night: release-controlplane's nightly records its `pin` (the pubkit
  it pins against the latest release) and `sync` (main's `pubkit sync --check`), passes
  as well as failures, with the versions, main's commit and run, and the fix, in the
  one append-only table `platform.pubkit_checks` (loaded from storage's
  `pubkit-checks` buffer).

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

**Setting it up.** The bot's token is a secret: Bitwarden's Sustenaut project keeps
it as `slack-bot-token`, and `pubkit.json`'s `secrets` list sends it here as
`SUSTENAUT_SLACK_BOT_TOKEN`:

```sh
./with-secrets ./pubsec app-secrets --check   # names and lengths only; sends nothing
./with-secrets ./pubsec app-secrets
```

The channel and the targets aren't secrets: they are the repository variables
`UPTIME_SLACK_CHANNEL` and `UPTIME_TARGETS`, which `pubkit.json`'s `variables` block
declares and the owner's state repository keeps (`pubfleet variables --apply` sets
them). To change the targets, change them there. The Bitwarden entries
`uptime-slack-channel` and `uptime-targets`, which used to send them, can be deleted
once the state repository tracks them. The bot must be in each channel it posts
to; a direct message needs nothing more.

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
| `need_drift` | warning | a deploy service's need the latest walk found drifted, or missing or blocked after a ready walk in the last 30 days; it ends when a walk finds it ready (an `unknown` need, one the walk couldn't check, is not drift) |
| `pubkit_drift` | warning | a repository on the release board whose latest nightly check (`platform.pubkit_checks`) failed: it pins an older pubkit than the latest release, or main fails `pubkit sync --check`; the post gives the fix, and the next night's pass ends it. The nightly records passes too, so the table is the night-by-night record for audits |

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

## The trends page

`observability.sustenaut.eu/trends/integrations` shows the last day, behind the team
sign-in: plain HTML from the server, with no script, never cached. It shows:

- **Signals**: those open, critical first, with their evidence, and those that ended in
  the last day, from `observability.signals`. Each subject links to its signal's page.
- **Calls by plugin**: each app's calls, errors (refused or unavailable) and their share,
  the typical latency (the bucket medians, weighted by calls) and the slowest, from
  `call_rollups` (calls to outside services only, not request totals).
- **Senders**: every sender and ingest pod seen in the last day, and every one
  `OBSERVABILITY_SENDERS` expects, with its last report and its state: reporting, on
  demand, or silent (an always-on sender quiet for more than 6 minutes).
- **Page times**: the newest 30 two-minute windows of each sender that answered
  requests, with their quickest, median and slowest answers, and cold starts marked.

It runs as `observability.page.main:app` in its own pod (`k8s/page.yaml`), reading
BigQuery with the reader's key. `k8s/oauth2-proxy.yaml` signs people in with the team
realm at auth.sustenaut.eu and lets in only those with the role `observability`; who has
it is the team access page, auth.sustenaut.eu/realms/team/access. Only the proxy may
reach the page (`k8s/admin/network-policy.yaml`), and the ingress routes everything to
the proxy. The sign-in client is sustenaut.eu's, for its team sites: the deploy walk
(below) adds this site to it with Sustenaut/auth's `register-app.py`, approved by a DNS
record, and puts it in the Secret `observability-oidc`.

## A signal's page

Each signal has a page of its own, behind the same sign-in, gathering what lies behind
it. A notifier's message links here. The address never changes, whether the signal is
open or has ended:

```
https://observability.sustenaut.eu/signals/<rule_id>/<started>/<subject>
```

`started` is the signal's `started_at` in UTC as `YYYYMMDDTHHMMSSZ`, with `.ffffff`
before the `Z` when it has microseconds. `subject` comes last, percent-encoded except
for `/`, so `example/app` reads as it is. `observability.links` makes the address
(`signal_url(rule_id, subject, started_at)`) and reads it back. It needs nothing installed,
so another repository can depend on this package for it alone.

The page shows:

- **The signal**: its rule and the rule's version, severity, subject, when it started, and
  whether it is open or how long it lasted, with its evidence.
- **The trend**: the value the rule tests, against its threshold, from the hour before the
  signal began to half an hour after it ended (or now), as an inline SVG with the signal's
  span shaded. It comes from the rule's optional `trend`, which `drops`, `storage_failures`,
  `slow_pages` and `plugin_errors` have; the other rules don't have one yet.
- **The windows around it**: the facts the evidence names over the same span. A sender's
  windows (reports, calls, drops, failed writes and page times), the ingest pod's
  (waiting and rejected files) for a project, or an app's calls to a plugin.
- **The rule's other signals** for the same subject in the last 30 days, each linking to
  its own page.
- **The rule**: its lookback and its query.

An address that names no signal, a rule there isn't, or a malformed time is a 404. The
page reads the same tables as the trends page, with the same key: the reader already sees
`observability.signals` and the call log datasets.

The page is read-only. Later it is where rules are configured: an edit there will open a
pull request here, so rules and their routes stay versioned files.

## Deploying

The evaluator runs on the shared k3s server, in namespace `observability`, as the
CronJob in `k8s/evaluator.yaml`: every two minutes, one run at a time, each stopped
if it overruns. It is the service account `evaluator`, which is the principal storage's
`signals` tenant lets write (`k8s:observability/evaluator`), with a projected token
for storage and no Kubernetes API token.

`.github/workflows/deploy.yml` builds the image (`Dockerfile`, from the hash-locked
`evaluator-requirements.lock`) on each merge to main and applies `k8s/` with pubkit's
`k8s-deploy.yml`, once `DEPLOY_OBSERVABILITY` is `on`. Its settings are the
repository variables `OBSERVABILITY_DATASETS` (the call log datasets, comma-separated)
and `OBSERVABILITY_SENDERS` (YAML or JSON, above), which become the ConfigMap
`evaluator-settings`. They aren't secrets, so they aren't in Bitwarden: `pubkit.json`'s
`variables` block names them, and the owner's state repository keeps their values and
sets them (`pubfleet variables --apply`, which then runs the deploy). By hand:

```sh
gh variable set OBSERVABILITY_DATASETS -R Sustenaut/observability --body 'calls_example,calls_other'
gh variable set OBSERVABILITY_SENDERS -R Sustenaut/observability --body '{"example": {"app": "always"}}'
```

pubkit.json's `deploy` block lists everything else it needs, and pubkit's deploy walk
checks each and makes what it can. To take it live, or bring it back in step, from a
checkout of this repository with Sustenaut/auth and Sustenaut/shared-infra checked out
beside it, on a machine on the admin tailnet, signed in to `gh` and `gcloud`:

```sh
./with-secrets ./pubdeploy walk --fulfil --server sustenaut --zones ../shared-infra/pubkit.json
```

It checks every need, prints the plan, and waits for a typed `yes`; then it makes each
missing need it can, over the admin channel (`ssh root@sustenaut`), and checks it again.
Every run can run again: what is ready is left alone. In order:

| Need | What the walk does |
|---|---|
| the namespace `observability` | the server's `sustenaut-app`, which makes it and its deploy identity |
| `gcp.service-account-key` | a new key of `observability-reader` (Terraform's, in shared-infra), written to Bitwarden as `observability-reader-key`, then put in the Secret `evaluator-bigquery-key`. A key that is no longer one of the account's live keys is drift, and a new one is made |
| `bitwarden.generated` | the page's cookie secret, `observability-cookie-secret`, made the first time and written to Bitwarden, then put in the Secret `observability-page-secrets` |
| `auth.sign-in-client` | the Secret `observability-oidc`, made on the server from the client kept there, so its secret never leaves the server |
| `k8s.manifests` | the page's network policy, `k8s/admin/network-policy.yaml` |
| the repository's secrets and deploy settings | from Bitwarden, as `pubsec app-secrets` sends them |
| `DEPLOY_OBSERVABILITY` and the rollout | the gate on, once everything before it is ready, and `deploy.yml` run and waited for |
| `service.health` | one run of the evaluator, from its CronJob, and `/healthz` |

A new key or cookie secret wants a Bitwarden token that may write: the walk asks for it
once, at a hidden prompt, and keeps it only in its process. A Secret it changes restarts
what reads it, such as the sign-in proxy.

Some needs it only checks, and says what a person does:

- **The sign-in client, the first time.** Until sustenaut.eu's client has this site, the
  need is blocked, and its fix is the command that prints a link and a code: sign in there
  as the registrant and confirm. auth.sustenaut.eu then answers with a TXT record, and the
  next `--fulfil` writes it into `../shared-infra/infra/auth-approvals.json`: open a pull
  request there, merge it, run `./with-secrets terraform -chdir=infra apply` in
  shared-infra, and walk again. Who may see the page is the `observability` column on the
  team access page, auth.sustenaut.eu/realms/team/access.
- **The `signals` tenant** in Sustenaut/storage's `tenants.json`, which lets the evaluator
  write (`k8s:observability/evaluator`), and integrations' `INGEST_SIGNALS`, whose
  `tenant` is `signals`, so the ingest pod loads what the evaluator writes. When one is
  missing, the fix is the entry to add, in storage, or in the owner's state file.
- **The variables** `OBSERVABILITY_DATASETS` and `OBSERVABILITY_SENDERS`, which must be set.
- **storage itself** (`upstream`) and the site's DNS record, from shared-infra's zone.

`./pubdeploy walk` without `--fulfil` (or `pubdeploy check`) changes nothing, and
`./pubdeploy walk --offline` checks only the files. `.github/workflows/deploy-check.yml`
walks it every 30 minutes, read-only, with the deploy key, and writes the walk to
storage's `plane` tenant; it fails
when a need is missing, drift or blocked. It can't check out shared-infra, so there the
DNS record is unknown, which fails nothing.

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
