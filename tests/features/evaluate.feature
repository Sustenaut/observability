Feature: The evaluator

  `observability evaluate` runs every rule against BigQuery, reads the
  signals still open from observability.signals, and prints the signals
  that start and end now, one JSON line each. Here BigQuery is a local
  stand-in that runs each query on fixture rows.

  Background:
    Given a scratch directory
    And the dataset "calls_example" holds "unhealthy"
    And the environment sets "OBSERVABILITY_DATASETS" to "calls_example"
    And the environment sets "OBSERVABILITY_SENDERS" to "example: {app: always, web: always}"
    And the environment does not set "OBSERVABILITY_STORAGE_URL"
    And a service account key in "credential.json", the credential file

  Scenario: Every breach starts a signal
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "storage_errors" for "example" as warning
    And it starts "sender_silent" for "example/web" with "last_seen" "2026-11-01T10:10:30Z"
    And it starts "plugin_errors" for "example/service/github.edit-pr"
    And it writes nothing for "storage_unreachable"
    And every signal started at 10:30 and has not ended

  Scenario: A rule with params records the thresholds it ran with in each signal it starts
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "sender_silent" for "example/web" as critical
    And the start of "sender_silent" for "example/web" records the thresholds "{"silent_minutes": 10}"
    And the start of "storage_errors" for "example" records no thresholds

  Scenario: OBSERVABILITY_THRESHOLDS sets a rule's threshold and severity, and its signals record them
    Given the environment sets "OBSERVABILITY_THRESHOLDS" to "{"version": 1, "rules": {"sender_silent": {"silent_minutes": 15, "severity": "warning"}}}"
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "sender_silent" for "example/web" as warning
    And the start of "sender_silent" for "example/web" records the thresholds "{"silent_minutes": 15}"

  Scenario: A threshold OBSERVABILITY_THRESHOLDS raises past a silence leaves it alone
    Given the environment sets "OBSERVABILITY_THRESHOLDS" to "{version: 1, rules: {sender_silent: {silent_minutes: 30}}}"
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "sender_silent"

  Scenario: OBSERVABILITY_THRESHOLDS set to its version and no rules changes nothing
    Given the environment sets "OBSERVABILITY_THRESHOLDS" to "{"version": 1, "rules": {}}"
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "sender_silent" for "example/web" as critical

  Scenario: A breach already open is not written again
    Given the open signal "storage_errors" for "example" since 10:10
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "storage_errors"

  Scenario: An open signal no longer in breach ends, keeping its start
    Given the open signal "sender_silent" for "example/app" since 10:10
    When the evaluator runs at 10:30
    Then it ends "sender_silent" for "example/app", started at 10:10

  Scenario: A signal that has ended is not open
    Given the signal "sender_silent" for "example/gone" from 10:00 to 10:10
    When the evaluator runs at 10:30
    Then it writes nothing for "example/gone"

  Scenario: An open signal whose rule is gone ends, saying so
    Given the open signal "retired_rule" for "example" since 10:10
    When the evaluator runs at 10:30
    Then it ends "retired_rule" for "example", started at 10:10
    And its evidence says "ended_because" "the rule is gone"

  Scenario: A rule whose query fails ends nothing, and the run fails
    Given the open signal "plugin_errors" for "example/service/slack.post" since 10:10
    And BigQuery refuses queries of "calls"
    When the evaluator runs at 10:30
    Then the exit code is 1
    And stderr mentions "plugin_errors failed, so its signals stay as they were"
    And it writes nothing for "example/service/slack.post"

  Scenario: A query BigQuery is still running is asked after again
    Given BigQuery answers each query only on the second ask
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "storage_errors" for "example" as warning

  Scenario: A query that never finishes fails its rule
    Given BigQuery never finishes a query
    When the evaluator runs at 10:30
    Then the exit code is 2
    And stderr mentions "did not finish"

  Scenario: An answer over several pages is read whole
    Given the environment sets "OBSERVABILITY_SENDERS" to "example: {web: always, gone: always}"
    And BigQuery answers one row a page
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "sender_silent" for "example/web" with "last_seen" "2026-11-01T10:10:30Z"
    And it starts "sender_silent" for "example/gone"

  Scenario: An external_account credential, the pod's with no key, is taken through Workload Identity
    Given a file "credential.json" holding the credential of "k8s/google-credential.yaml"
    When the evaluator's warehouse is made from the credential file
    Then the result's "token" is "FederatedToken"
    And the result's "project" is "sustenaut"

  Scenario: Without a time it evaluates now
    When the evaluator runs now
    Then it succeeds

  Scenario Outline: Its configuration is checked
    Given the environment sets "<setting>" to "<value>"
    When the evaluator runs at 10:30
    Then the exit code is 2
    And stderr mentions "<message>"

    Examples:
      | setting                    | value                     | message                                         |
      | OBSERVABILITY_SENDERS      | example: [                | OBSERVABILITY_SENDERS is not YAML               |
      | OBSERVABILITY_SENDERS      | [1]                       | OBSERVABILITY_SENDERS maps each project         |
      | OBSERVABILITY_SENDERS      | elsewhere: {app: always}  | OBSERVABILITY_SENDERS names elsewhere           |
      | OBSERVABILITY_SENDERS      | example: {}               | example maps each sender prefix                 |
      | OBSERVABILITY_SENDERS      | example: {app: sometimes} | example/app is always or on-demand, not sometimes |
      | OBSERVABILITY_THRESHOLDS   | version: [                                                     | OBSERVABILITY_THRESHOLDS is not YAML |
      | OBSERVABILITY_THRESHOLDS   | [1]                                                            | OBSERVABILITY_THRESHOLDS is a mapping with a version and its rules |
      | OBSERVABILITY_THRESHOLDS   | {rules: {}}                                                    | OBSERVABILITY_THRESHOLDS is a mapping with a version and its rules |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rule: {}}                                         | OBSERVABILITY_THRESHOLDS has a version and rules, and no rule |
      | OBSERVABILITY_THRESHOLDS   | {version: 2, rules: {}}                                        | OBSERVABILITY_THRESHOLDS is version 1, not 2 |
      | OBSERVABILITY_THRESHOLDS   | {version: true, rules: {}}                                     | OBSERVABILITY_THRESHOLDS is version 1, not True |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: [sender_silent]}                           | OBSERVABILITY_THRESHOLDS: rules maps each rule to its thresholds |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {quiet: {silent_minutes: 5}}}              | OBSERVABILITY_THRESHOLDS names the rule quiet, which there is not |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {sender_silent: 5}}                        | OBSERVABILITY_THRESHOLDS: sender_silent maps each of its params to a number |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {sender_silent: {minutes: 5}}}             | sender_silent has no param minutes; its params are silent_minutes |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {drops: {limit: 5}}}                       | drops has no param limit; it has no params |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {sender_silent: {silent_minutes: soon}}}   | sender_silent's silent_minutes is a number, not soon |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {sender_silent: {silent_minutes: false}}}  | sender_silent's silent_minutes is a number, not False |
      | OBSERVABILITY_THRESHOLDS   | {version: 1, rules: {sender_silent: {severity: loud}}}         | sender_silent's severity is critical, warning, info, not loud |
      | OBSERVABILITY_GOOGLE_CREDENTIAL_FILE | /nonexistent    | OBSERVABILITY_GOOGLE_CREDENTIAL_FILE is not a readable JSON file |

  Scenario Outline: A setting it needs is checked
    Given the environment does not set "<setting>"
    When the evaluator runs at 10:30
    Then the exit code is 2
    And stderr mentions "<message>"

    Examples:
      | setting                              | message                                                 |
      | OBSERVABILITY_DATASETS               | no dataset: set OBSERVABILITY_DATASETS                  |
      | OBSERVABILITY_GOOGLE_CREDENTIAL_FILE | no credential: set OBSERVABILITY_GOOGLE_CREDENTIAL_FILE |

  Scenario: A credential file that is neither kind is said
    Given a file "credential.json" holding "{"not": "a key"}"
    When the evaluator runs at 10:30
    Then the exit code is 2
    And stderr mentions "OBSERVABILITY_GOOGLE_CREDENTIAL_FILE is neither an external_account credential nor a service account's key"

  Scenario: BigQuery's answers are read by their types
    When BigQuery answers a row of every type
    Then the result is:
      | n | x   | b    | t                         | s | l      | z    |
      | 3 | 0.5 | true | 2025-11-01 12:26:40+00:00 | a | [1, 2] | null |

  Scenario: With storage, the run's signals are written to the signals tenant, one file
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    When the evaluator runs at 10:30
    Then it succeeds
    And one file of 10 signals is written to inbox/signals/2026-11-01/

  Scenario: A start written but not loaded yet is open, so it isn't written again
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And the tenant holds a start of "storage_errors" for "example" at 10:28, not loaded yet
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "storage_errors"

  Scenario: An end written but not loaded yet closes the open signal, so it isn't ended twice
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And the open signal "sender_silent" for "example/app" since 10:10
    And the tenant holds an end of "sender_silent" for "example/app" started at 10:10, not loaded yet
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "sender_silent" on "example/app"

  Scenario: An end of another start leaves the open signal open
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And the open signal "sender_silent" for "example/app" since 10:10
    And the tenant holds an end of "sender_silent" for "example/app" started at 09:00, not loaded yet
    When the evaluator runs at 10:30
    Then it ends "sender_silent" for "example/app", started at 10:10

  Scenario: A file loaded between its listing and its reading is skipped
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And a file in the tenant is loaded between its listing and its reading
    When the evaluator runs at 10:30
    Then it succeeds

  Scenario: A run with nothing to say writes no file
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And the dataset "calls_fine" holds "healthy"
    And the environment sets "OBSERVABILITY_DATASETS" to "calls_fine"
    And the environment sets "OBSERVABILITY_SENDERS" to "fine: {app: always}"
    When the evaluator runs at 10:30
    Then it succeeds
    And nothing is written to the tenant
    And stderr does not mention "wrote"

  Scenario: Signals storage refuses fail the run
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And storage refuses writes
    When the evaluator runs at 10:30
    Then the exit code is 1
    And stderr mentions "the signals could not be written"

  Scenario: Without the signals not loaded yet, nothing is evaluated
    Given the environment sets "OBSERVABILITY_STORAGE_URL" to "https://storage.example.test"
    And storage does not answer listings
    When the evaluator runs at 10:30
    Then the exit code is 2
    And stderr mentions "could not read the open signals"

  # A mismatch fails only at run time, as Google's STS refusing the token: the
  # evaluator's and the page's projected tokens, and the credential's audience,
  # are the services pool's provider (Sustenaut/shared-infra's services_google output).
  Scenario: The credential names the services pool's provider, and the token the pods mount
    When the credential in "k8s/google-credential.yaml" is read
    Then the result's "audience" is "//iam.googleapis.com/projects/948171295184/locations/global/workloadIdentityPools/services/providers/sustenaut-k3s"
    And the result's "credential_source.file" is "/var/run/secrets/google/token"

  Scenario: Each pod's projected token has the provider as its audience, where the credential reads it
    When the pods' Google credentials are read
    Then the result is:
      | pod       | account   | automount | audience                                                                                                     | token                         | credential_dir | credential                  |
      | evaluator | evaluator | false     | //iam.googleapis.com/projects/948171295184/locations/global/workloadIdentityPools/services/providers/sustenaut-k3s | /var/run/secrets/google/token | /etc/google    | /etc/google/credential.json |
      | page      | page      | false     | //iam.googleapis.com/projects/948171295184/locations/global/workloadIdentityPools/services/providers/sustenaut-k3s | /var/run/secrets/google/token | /etc/google    | /etc/google/credential.json |
