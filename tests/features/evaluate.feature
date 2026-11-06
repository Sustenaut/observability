Feature: The evaluator

  `observability evaluate` runs every rule against BigQuery, reads the
  signals still open from observability.signals, and prints the signals
  that start and end now, one JSON line each. Here BigQuery is a local
  stand-in that runs each query on fixture rows.

  Background:
    Given the dataset "calls_example" holds "unhealthy"
    And OBSERVABILITY_DATASETS is "calls_example"
    And OBSERVABILITY_SENDERS is "example: {app: always, web: always}"
    And a service account key in OBSERVABILITY_BIGQUERY_KEY

  Scenario: Every breach starts a signal
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "storage_unreachable" for "example" as critical
    And it starts "sender_silent" for "example/web" with "last_seen" "2026-11-01T10:10:30Z"
    And it starts "plugin_errors" for "example/service/github.edit-pr"
    And every signal started at 10:30 and has not ended

  Scenario: A breach already open is not written again
    Given the open signal "storage_unreachable" for "example" since 10:10
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "storage_unreachable"

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
    Then it fails with code 1
    And stderr mentions "plugin_errors failed, so its signals stay as they were"
    And it writes nothing for "example/service/slack.post"

  Scenario: A query BigQuery is still running is asked after again
    Given BigQuery answers each query only on the second ask
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "storage_unreachable" for "example" as critical

  Scenario: A query that never finishes fails its rule
    Given BigQuery never finishes a query
    When the evaluator runs at 10:30
    Then it fails with code 2
    And stderr mentions "did not finish"

  Scenario: An answer over several pages is read whole
    Given OBSERVABILITY_SENDERS is "example: {web: always, gone: always}"
    And BigQuery answers one row a page
    When the evaluator runs at 10:30
    Then it succeeds
    And it starts "sender_silent" for "example/web" with "last_seen" "2026-11-01T10:10:30Z"
    And it starts "sender_silent" for "example/gone"

  Scenario: A key in base64, as Bitwarden keeps it, is taken
    Given the service account key is in base64
    When the evaluator runs at 10:30
    Then it succeeds

  Scenario: Without a time it evaluates now
    When the evaluator runs now
    Then it succeeds

  Scenario Outline: Its configuration is checked
    Given <setting> is "<value>"
    When the evaluator runs at 10:30
    Then it fails with code 2
    And stderr mentions "<message>"

    Examples:
      | setting                    | value                     | message                                         |
      | OBSERVABILITY_DATASETS     |                           | no dataset: set OBSERVABILITY_DATASETS          |
      | OBSERVABILITY_SENDERS      | example: [                | OBSERVABILITY_SENDERS is not YAML               |
      | OBSERVABILITY_SENDERS      | [1]                       | OBSERVABILITY_SENDERS maps each project         |
      | OBSERVABILITY_SENDERS      | elsewhere: {app: always}  | OBSERVABILITY_SENDERS names elsewhere           |
      | OBSERVABILITY_SENDERS      | example: {}               | example maps each sender prefix                 |
      | OBSERVABILITY_SENDERS      | example: {app: sometimes} | example/app is always or on-demand, not sometimes |
      | OBSERVABILITY_BIGQUERY_KEY | {"not": "a key"}          | OBSERVABILITY_BIGQUERY_KEY is not a service account's key |
      | OBSERVABILITY_BIGQUERY_KEY | not json                  | OBSERVABILITY_BIGQUERY_KEY is not a service account's key |

  Scenario: BigQuery's answers are read by their types
    When BigQuery answers a row of every type
    Then the row reads as Python values
