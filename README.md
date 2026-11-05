# observability

Trends across Sustenaut's services, behind the team sign-in.

Each service logs its calls to outside services (see
[integrations](https://github.com/Sustenaut/integrations)). Observability reads
those logs, turns them into signals with versioned rules, and shows the trends.
It gathers and reports; it never acts on what it finds. Acting on a signal is
another service's job.

This repository is code only. Which services and datasets it reads is
configuration, given where it runs, so nothing here names them.

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
