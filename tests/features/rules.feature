Feature: Rules over the facts

  Each rule is a versioned query over the facts that returns one row per
  subject in breach. Here each runs on fixture rows at 10:30, locally.

  Background:
    Given the dataset "calls_example" holds "unhealthy"
    And the dataset "calls_other" holds "other-project"
    And the senders are "example: {app: always, web: always, plan: on-demand, missing: always}"

  Scenario: An always-on sender silent for more than 6 minutes, or never seen; on-demand ones are left alone
    When the rule "sender_silent" runs at 10:30
    Then it finds
      | subject         | last_seen |
      | example/missing |           |
      | example/web     | 10:10     |

  Scenario: A project the ingest pod has reported nothing for
    When the rule "ingest_silent" runs at 10:30
    Then it finds
      | subject | last_seen |
      | other   |           |

  Scenario: Storage did not answer the ingest pod's latest cycle
    When the rule "storage_unreachable" runs at 10:30
    Then it finds
      | subject | problems               |
      | example | storage did not answer |

  Scenario: A file waiting more than 10 minutes, by the latest cycle
    When the rule "inbox_stale" runs at 10:30
    Then it finds
      | subject | waiting_files | waiting_oldest_seconds |
      | example | 4             | 900                    |

  Scenario: Files that could not load
    When the rule "rejected_files" runs at 10:30
    Then it finds
      | subject | rejected_files | rejected_oldest_seconds |
      | example | 2              | 4000                    |

  Scenario: Load jobs near the day's limit
    When the rule "load_jobs_near_limit" runs at 10:30
    Then it finds
      | subject | jobs_today | status_jobs_today |
      | example | 1250       | 300               |

  Scenario: A sender that failed to write to storage in the last 6 minutes
    When the rule "storage_failures" runs at 10:30
    Then it finds
      | subject     | failed_writes |
      | example/app | 1             |

  Scenario: A sender that dropped records in the last 6 minutes
    When the rule "drops" runs at 10:30
    Then it finds
      | subject     | dropped |
      | example/app | 3       |

  Scenario: A warm sender slower than 5 seconds
    When the rule "slow_pages" runs at 10:30
    Then it finds
      | subject     | slowest_ms |
      | example/app | 7000       |

  Scenario: More than 5% of a plugin's calls failing over 30 minutes; 4% and request totals are not counted
    When the rule "plugin_errors" runs at 10:30
    Then it finds
      | subject                        | call_count | error_count | unavailable_count |
      | example/service/github.edit-pr | 25         | 3           | 3                 |

  Scenario: The day's share of answering windows that began cold
    When the rule "cold_start_share" runs at 10:30
    Then it finds
      | subject     | cold_windows | windows | share |
      | example/app | 1            | 2       | 0.5   |

  Scenario Outline: A healthy project breaks no rule
    Given a fresh dataset "calls_fine" holding "healthy"
    And the senders are "fine: {app: always}"
    When the rule "<rule>" runs at 10:30 over "calls_fine"
    Then it finds nothing

    Examples:
      | rule                 |
      | sender_silent        |
      | ingest_silent        |
      | storage_unreachable  |
      | inbox_stale          |
      | rejected_files       |
      | load_jobs_near_limit |
      | storage_failures     |
      | drops                |
      | slow_pages           |
      | plugin_errors        |
      | cold_start_share     |
      | need_drift           |
      | pubkit_drift         |

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
    Then it finds
      | subject                                        | state   | found_at | ready_at | page                                                      |
      | Sustenaut/notifier/notifier/k8s.secret:slack   | missing | 10:00    | 09:00    | https://convergence.sustenaut.eu/services/Sustenaut/notifier |
      | Sustenaut/auth/auth/github.secret:KEY          | drift   | 10:00    |          | https://convergence.sustenaut.eu/services/Sustenaut/auth     |
      | Sustenaut/auth/auth/upstream:storage           | blocked | 10:00    | 09:30    | https://convergence.sustenaut.eu/services/Sustenaut/auth     |

  Scenario: A check failing in the latest night opens a signal, and the next night's pass ends it
    Given the nightly checks found
      | night | repository           | check | status  | pinned | latest | fix                                               | run_url |
      | 08:00 | Sustenaut/pubhost    | pin   | fail    | 0.35.1 | 0.37.0 | `git latest && ./pubkit bump`, then open its PR   |         |
      | 09:00 | Sustenaut/pubhost    | pin   | fail    | 0.35.1 | 0.37.0 | `git latest && ./pubkit bump`, then open its PR   |         |
      | 08:00 | Sustenaut/pubtheme   | sync  | fail    | 0.37.0 | 0.37.0 | `git latest && ./pubkit sync`, then open its PR   | https://github.com/run/7 |
      | 09:00 | Sustenaut/pubtheme   | sync  | pass    | 0.37.0 | 0.37.0 |                                                   | https://github.com/run/8 |
      | 09:00 | Sustenaut/pubtheme   | pin   | pass    | 0.37.0 | 0.37.0 |                                                   |         |
      | 09:00 | Sustenaut/docs       | pin   | unknown |        | 0.37.0 |                                                   |         |
      | 09:00 | Sustenaut/ui         | sync  | fail    | 0.37.0 | 0.37.0 | `git latest && ./pubkit sync`, then open its PR   | https://github.com/run/9 |
    When the rule "pubkit_drift" runs at 10:30
    Then it finds
      | subject                | check | status | pinned | latest | fix                                             | run_url                  |
      | Sustenaut/pubhost/pin  | pin   | fail   | 0.35.1 | 0.37.0 | `git latest && ./pubkit bump`, then open its PR |                          |
      | Sustenaut/ui/sync      | sync  | fail   | 0.37.0 | 0.37.0 | `git latest && ./pubkit sync`, then open its PR | https://github.com/run/9 |

  Scenario: No night, no drift
    Given the nightly checks found
      | night | repository | check | status |
    When the rule "pubkit_drift" runs at 10:30
    Then it finds nothing

  Scenario: No walk, no drift
    Given the convergence engine's walks found
      | walk  | repository          | need             | state   |
    When the rule "need_drift" runs at 10:30
    Then it finds nothing

  Scenario: With no always-on sender, none is silent
    Given the senders are "example: {plan: on-demand}"
    When the rule "sender_silent" runs at 10:30
    Then it finds nothing

  Scenario Outline: A rule file that is wrong is refused
    When a rule file "<name>" reads "<yaml>"
    Then reading it fails with "<message>"

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
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: high, query: q}} | r.yaml: a trend's threshold is a number |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: true, query: q}} | r.yaml: a trend's threshold is a number |
      | r     | {id: r, version: 1, severity: info, summary: s, lookback_minutes: 5, query: q, trend: {label: l, threshold: 1, query: 'SELECT {{later}}'}} | r.yaml: there is no {{later}} |

  Scenario: The rules are listed with their versions and severities
    When I list the rules
    Then the list has "sender_silent\tversion 1\tcritical"
    And the list has "cold_start_share\tversion 1\tinfo"
