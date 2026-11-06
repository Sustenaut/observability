# observability

Trends across Sustenaut's services, behind the team sign-in.

Each service logs its calls to outside services (see
[integrations](https://github.com/Sustenaut/integrations)). Observability reads
those logs, turns them into signals with versioned rules, and shows the trends.
It gathers and reports; it never acts on what it finds. Acting on a signal is
another service's job.

This repository is code only. Which services and datasets it reads is
configuration, given where it runs, so nothing here names them.

## Uptime

`.github/workflows/uptime.yml` probes each site every five minutes from
GitHub Actions, off the server it watches, so it still reports when that
server is down. Every other part of observability reads what services
report; this is the one check that doesn't depend on them.

- **Targets** are the repository variable `UPTIME_TARGETS`, a JSON list of
  `{"name", "url", "expect_status"}` (`expect_status` defaults to 200). A
  redirect is compared, not followed, so a site behind sign-in can be
  probed by the redirect it answers with. No target is named here, and
  with the variable unset the workflow does nothing.
- **Down** means two runs in a row failed: no answer within 10 s, or a
  status other than the one expected, each run trying a failing target
  twice. The state between runs, each target's failures in a row, is a
  small file, `uptime-state.json` in the working directory, kept in the Actions cache. If the cache is lost, the next run
  starts afresh.
- **Alerts:** going down and recovering are posted to the
  `UPTIME_SLACK_WEBHOOK` secret, a Slack incoming webhook, directly. Every
  other Slack post goes through the integrations service, but that service
  runs on the server being watched. So this call is like GitHub Actions'
  own calls to vendors: reported in `integrations.json`, not routed.
  Without the secret, nothing is posted. A run fails while any target is
  down, so GitHub's failed-run email is the backup.

```sh
UPTIME_TARGETS='[{"name": "example", "url": "https://example.test/healthz"}]' \
  PYTHONPATH=src python3 -m observability.uptime
```

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
