Feature: Rules over the facts

  Each rule is a versioned query over the facts that returns one row per
  subject in breach. Here each runs on fixture rows at 10:30, locally.

  Background:
    Given the dataset "calls_example" holds "unhealthy"
    And the dataset "calls_other" holds "other-project"
    And the senders are "example: {app: always, web: always, plan: on-demand, missing: always}"

  Scenario: An always-on sender silent for more than 10 minutes, or never seen; on-demand ones are left alone
    When the rule "sender_silent" runs at 10:30
    Then the result is:
      | subject         | last_seen |
      | example/missing |           |
      | example/web     | 10:10     |

  Scenario: A sender quiet for 8 minutes is not silent yet
    When the rule "sender_silent" runs at 10:18
    Then the result is:
      | subject         | last_seen |
      | example/missing |           |

  Scenario: Every project the ingest pod has reported nothing for, as one signal
    When the rule "ingest_silent" runs at 10:30
    Then the result is:
      | subject | projects | oldest_last_seen |
      | ingest  | other    |                  |

  Scenario Outline: An ingest pod that reports slowly is not silent before 15 minutes
    Given the ingest pod's cycles for "calls_slow" were
      | at       | storage_ok |
      | 10:00:00 | true       |
      | <last>   | true       |
    And the senders are "{}"
    When the rule "ingest_silent" runs at 10:30 over "calls_slow"
    Then the result is empty

    Examples:
      | last     |
      | 10:23:00 |
      | 10:17:00 |

  Scenario: An ingest pod quiet for 16 minutes is silent, for every project it has gone quiet for
    Given the ingest pod's cycles for "calls_slow" were
      | at       | storage_ok |
      | 10:14:00 | true       |
    And the ingest pod's cycles for "calls_quiet" were
      | at       | storage_ok |
      | 10:12:00 | true       |
    And the ingest pod's cycles for "calls_busy" were
      | at       | storage_ok |
      | 10:29:00 | true       |
    And the senders are "{}"
    When the rule "ingest_silent" runs at 10:30 over "calls_slow" and "calls_quiet" and "calls_busy"
    Then the result is:
      | subject | projects   | oldest_last_seen |
      | ingest  | quiet,slow | 10:12            |

  Scenario: A threshold set in OBSERVABILITY_THRESHOLDS changes what a rule finds
    Given the ingest pod's cycles for "calls_slow" were
      | at       | storage_ok |
      | 10:14:00 | true       |
    And the thresholds are "{version: 1, rules: {ingest_silent: {silent_minutes: 20}}}"
    And the senders are "{}"
    When the rule "ingest_silent" runs at 10:30 over "calls_slow"
    Then the result is empty

  Scenario: Storage failing one project's latest cycle is storage_errors' alone
    When the rule "storage_errors" runs at 10:30
    Then the result is:
      | subject | problems               |
      | example | storage did not answer |
    When the rule "storage_unreachable" runs at 10:30
    Then the result is empty

  Scenario: Storage failing 3 of the latest 5 cycles, across projects, is storage_unreachable
    Given the ingest pod's cycles for "calls_a" were
      | at       | storage_ok | problems               |
      | 10:12:10 | false      | storage did not answer |
      | 10:20:10 | false      | storage did not answer |
      | 10:22:10 | true       |                        |
      | 10:24:10 | false      | storage did not answer |
      | 10:26:10 | true       |                        |
      | 10:28:10 | true       |                        |
    And the ingest pod's cycles for "calls_b" were
      | at       | storage_ok | problems               |
      | 10:24:10 | false      | storage answered 503   |
      | 10:28:10 | false      | storage answered 503   |
    And the senders are "{}"
    When the rule "storage_unreachable" runs at 10:30 over "calls_a" and "calls_b"
    Then the result is:
      | subject | failed | cycles | projects | latest_failure | problems             |
      | storage | 3      | 5      | a,b      | 10:28          | storage answered 503 |

  Scenario: Storage failing 2 of the latest 5 cycles is not storage_unreachable, whatever failed before them
    Given the ingest pod's cycles for "calls_a" were
      | at       | storage_ok |
      | 10:12:10 | false      |
      | 10:14:10 | false      |
      | 10:20:10 | true       |
      | 10:22:10 | true       |
      | 10:24:10 | false      |
      | 10:26:10 | true       |
      | 10:28:10 | false      |
    And the senders are "{}"
    When the rule "storage_unreachable" runs at 10:30 over "calls_a"
    Then the result is empty
    When the rule "storage_errors" runs at 10:30 over "calls_a"
    Then the result is:
      | subject | bucket |
      | a       | 10:28  |

  Scenario: OBSERVABILITY_THRESHOLDS can make storage_unreachable stricter
    Given the ingest pod's cycles for "calls_a" were
      | at       | storage_ok |
      | 10:24:10 | false      |
      | 10:26:10 | true       |
      | 10:28:10 | false      |
    And the thresholds are "{version: 1, rules: {storage_unreachable: {failed_cycles: 2, window_cycles: 3}}}"
    And the senders are "{}"
    When the rule "storage_unreachable" runs at 10:30 over "calls_a"
    Then the result is:
      | subject | failed | cycles | projects |
      | storage | 2      | 3      | a        |

  Scenario: A file waiting more than 10 minutes, by the latest cycle
    When the rule "inbox_stale" runs at 10:30
    Then the result is:
      | subject | waiting_files | waiting_oldest_seconds |
      | example | 4             | 900                    |

  Scenario: Files that could not load
    When the rule "rejected_files" runs at 10:30
    Then the result is:
      | subject | rejected_files | rejected_oldest_seconds |
      | example | 2              | 4000                    |

  Scenario: Load jobs near the day's limit
    When the rule "load_jobs_near_limit" runs at 10:30
    Then the result is:
      | subject | jobs_today | status_jobs_today |
      | example | 1250       | 300               |

  Scenario: A sender that failed to write to storage in the last 6 minutes
    When the rule "storage_failures" runs at 10:30
    Then the result is:
      | subject     | failed_writes |
      | example/app | 1             |

  Scenario: A sender that dropped records in the last 6 minutes
    When the rule "drops" runs at 10:30
    Then the result is:
      | subject     | dropped |
      | example/app | 3       |

  Scenario: A warm sender slower than 5 seconds
    When the rule "slow_pages" runs at 10:30
    Then the result is:
      | subject     | slowest_ms |
      | example/app | 7000       |

  Scenario: More than 5% of a plugin's calls failing over 30 minutes; 4% and request totals are not counted
    When the rule "plugin_errors" runs at 10:30
    Then the result is:
      | subject                        | call_count | error_count | unavailable_count |
      | example/service/github.edit-pr | 25         | 3           | 3                 |

  Scenario: The day's share of answering windows that began cold
    When the rule "cold_start_share" runs at 10:30
    Then the result is:
      | subject     | cold_windows | windows | share |
      | example/app | 1            | 2       | 0.5   |

  Scenario Outline: A healthy project breaks no rule
    Given a fresh dataset "calls_fine" holding "healthy"
    And the senders are "fine: {app: always}"
    When the rule "<rule>" runs at 10:30 over "calls_fine"
    Then the result is empty

    Examples:
      | rule                 |
      | sender_silent        |
      | ingest_silent        |
      | storage_unreachable  |
      | storage_errors       |
      | inbox_stale          |
      | rejected_files       |
      | load_jobs_near_limit |
      | storage_failures     |
      | drops                |
      | slow_pages           |
      | plugin_errors        |
      | cold_start_share     |
      | need_drift           |
      | pubrules_drift         |

  Scenario: A need that left ready is drift until a walk finds it ready again
    Given the convergence engine's walks found
      | walk  | repository          | need                    | state   |
      | 09:00 | Sustenaut/notifier  | k8s.secret:slack        | ready   |
      | 09:30 | Sustenaut/notifier  | k8s.secret:slack        | missing |
      | 10:00 | Sustenaut/notifier  | k8s.secret:slack        | missing |
      | 09:30 | Sustenaut/notifier  | github.gate:DEPLOY      | ready   |
      | 10:00 | Sustenaut/notifier  | github.gate:DEPLOY      | ready   |
      | 09:30 | Sustenaut/auth      | bitwarden.secret:a      | ready   |
      | 10:00 | Sustenaut/auth      | bitwarden.secret:a      | unknown |
      | 09:30 | Sustenaut/auth      | dns.site:auth           | missing |
      | 10:00 | Sustenaut/auth      | dns.site:auth           | missing |
      | 09:00 | Sustenaut/auth      | k8s.secret:oidc         | ready   |
      | 09:30 | Sustenaut/auth      | k8s.secret:oidc         | drift   |
      | 10:00 | Sustenaut/auth      | k8s.secret:oidc         | ready   |
      | 09:30 | Sustenaut/auth      | github.secret:KEY       | drift   |
      | 10:00 | Sustenaut/auth      | github.secret:KEY       | drift   |
      | 09:30 | Sustenaut/auth      | upstream:storage        | ready   |
      | 10:00 | Sustenaut/auth      | upstream:storage        | blocked |
    When the rule "need_drift" runs at 10:30
    Then the result is:
      | subject                                        | state   | found_at | ready_at | page                                                      |
      | Sustenaut/auth/auth/github.secret:KEY          | drift   | 10:00    |          | https://convergence.sustenaut.eu/services/Sustenaut/auth     |
      | Sustenaut/auth/auth/upstream:storage           | blocked | 10:00    | 09:30    | https://convergence.sustenaut.eu/services/Sustenaut/auth     |
      | Sustenaut/notifier/notifier/k8s.secret:slack   | missing | 10:00    | 09:00    | https://convergence.sustenaut.eu/services/Sustenaut/notifier |

  Scenario: A check failing in the latest night opens a signal, and the next night's pass ends it
    Given the nightly checks found
      | night | repository           | check | status  | pinned | latest | fix                                               | run_url |
      | 08:00 | Sustenaut/pubhost    | pin   | fail    | 0.35.1 | 0.37.0 | `git latest && ./pubrules bump`, then open its PR   |         |
      | 09:00 | Sustenaut/pubhost    | pin   | fail    | 0.35.1 | 0.37.0 | `git latest && ./pubrules bump`, then open its PR   |         |
      | 08:00 | Sustenaut/pubtheme   | sync  | fail    | 0.37.0 | 0.37.0 | `git latest && ./pubrules sync`, then open its PR   | https://github.com/run/7 |
      | 09:00 | Sustenaut/pubtheme   | sync  | pass    | 0.37.0 | 0.37.0 |                                                   | https://github.com/run/8 |
      | 09:00 | Sustenaut/pubtheme   | pin   | pass    | 0.37.0 | 0.37.0 |                                                   |         |
      | 09:00 | Sustenaut/docs       | pin   | unknown |        | 0.37.0 |                                                   |         |
      | 09:00 | Sustenaut/ui         | sync  | fail    | 0.37.0 | 0.37.0 | `git latest && ./pubrules sync`, then open its PR   | https://github.com/run/9 |
    When the rule "pubrules_drift" runs at 10:30
    Then the result is:
      | subject                | check | status | pinned | latest | fix                                             | run_url                  |
      | Sustenaut/pubhost/pin  | pin   | fail   | 0.35.1 | 0.37.0 | `git latest && ./pubrules bump`, then open its PR |                          |
      | Sustenaut/ui/sync      | sync  | fail   | 0.37.0 | 0.37.0 | `git latest && ./pubrules sync`, then open its PR | https://github.com/run/9 |

  Scenario: No night, no drift
    Given the nightly checks found
      | night | repository | check | status |
    When the rule "pubrules_drift" runs at 10:30
    Then the result is empty

  Scenario: No walk, no drift
    Given the convergence engine's walks found
      | walk  | repository          | need             | state   |
    When the rule "need_drift" runs at 10:30
    Then the result is empty

  Scenario: With no always-on sender, none is silent
    Given the senders are "example: {plan: on-demand}"
    When the rule "sender_silent" runs at 10:30
    Then the result is empty

  Scenario Outline: A rule file that is wrong is refused
    When a rule file "<name>" reads "<yaml>"
    Then it is refused, saying "<message>"

    Examples:
      | name  | yaml                                                                                                   | message                                                   |
      | r     | [1]                                                                                                    | r.yaml: a rule is a mapping                               |
      | r     | {id: r, version: 1}                                                                                    | r.yaml: no lookback_minutes, query, severity, summary     |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, owner: me}              | r.yaml: no setting owner                                  |
      | r     | {id: other, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q}                     | r.yaml: its id is other                                   |
      | r     | {id: r, version: 1, severity: loud, summary: s, lookback_minutes: 5, query: q}                         | r.yaml: severity is critical, warning, info, not loud     |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 1, query: q}                         | r.yaml: lookback_minutes is a whole number of minutes     |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT * FROM {{fact:nope}}'} | r.yaml: there is no fact nope                         |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{later}}'}        | r.yaml: there is no {{later}}                             |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l}}      | r.yaml: a trend has label, query, threshold               |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: [1]}             | r.yaml: a trend has label, query, threshold               |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: high, query: q}} | r.yaml: a trend's threshold high is not among its params |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: true, query: q}} | r.yaml: a trend's threshold is a number, or one of its params |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: 1, query: 'SELECT {{later}}'}} | r.yaml: there is no {{later}} |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{fact:Calls}}'}    | r.yaml: there is no {{fact:Calls}}                        |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}'}   | r.yaml: {{param:limit}} is not among its params           |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:Limit}}', params: {limit: 1}} | r.yaml: there is no {{param:Limit}} |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, params: {limit: 1}}      | r.yaml: no query uses the param limit                     |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, params: [1]}             | r.yaml: params maps each name to a number                 |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, params: {Limit: 1}}      | r.yaml: a param's name is lowercase letters and underscores, not Limit |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, params: {limit: ten}}    | r.yaml: the param limit is a finite number above 0, not ten |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, params: {limit: true}}   | r.yaml: the param limit is a finite number above 0, not True |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}', params: {limit: .nan}} | r.yaml: the param limit is a finite number above 0, not nan |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}', params: {limit: .inf}} | r.yaml: the param limit is a finite number above 0, not inf |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}', params: {limit: -.inf}} | r.yaml: the param limit is a finite number above 0, not -inf |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}', params: {limit: 0}} | r.yaml: the param limit is a finite number above 0, not 0 |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}}', params: {limit: -1}} | r.yaml: the param limit is a finite number above 0, not -1 |

  Scenario: A rule's params fill its query, and a trend's threshold may be one of them
    When a rule file "r" reads "{id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: 'SELECT {{param:limit}} AS a, {{param:share}} AS b', params: {limit: 10, share: 0.25}, trend: {label: l, threshold: limit, query: 'SELECT {{param:share}} AS value'}}"
    Then it is not refused
    When the rule file "r" is rendered with the thresholds "{limit: 12}"
    Then the result is:
      """
      {"query": "SELECT 12 AS a, 0.25 AS b", "trend": "SELECT 0.25 AS value", "threshold": 12.0}
      """

  Scenario: The rules are listed with their versions and severities
    When the rules are listed
    Then it succeeds
    And it prints "sender_silent	version 2	critical"
    And it prints "storage_errors	version 1	warning"
    And it prints "cold_start_share	version 1	info"
