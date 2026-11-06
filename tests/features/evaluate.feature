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

  Scenario: With storage, the run's signals are written to the signals tenant, one file
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    When the evaluator runs at 10:30
    Then it succeeds
    And one file of 10 signals is written to inbox/signals/2026-11-01/

  Scenario: A start written but not loaded yet is open, so it isn't written again
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And the tenant holds a start of "storage_unreachable" for "example" at 10:28, not loaded yet
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "storage_unreachable"

  Scenario: An end written but not loaded yet closes the open signal, so it isn't ended twice
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And the open signal "sender_silent" for "example/app" since 10:10
    And the tenant holds an end of "sender_silent" for "example/app" started at 10:10, not loaded yet
    When the evaluator runs at 10:30
    Then it succeeds
    And it writes nothing for "sender_silent" on "example/app"

  Scenario: An end of another start leaves the open signal open
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And the open signal "sender_silent" for "example/app" since 10:10
    And the tenant holds an end of "sender_silent" for "example/app" started at 09:00, not loaded yet
    When the evaluator runs at 10:30
    Then it ends "sender_silent" for "example/app", started at 10:10

  Scenario: A file loaded between its listing and its reading is skipped
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And a file in the tenant is loaded between its listing and its reading
    When the evaluator runs at 10:30
    Then it succeeds

  Scenario: A run with nothing to say writes no file
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And the dataset "calls_fine" holds "healthy"
    And OBSERVABILITY_DATASETS is "calls_fine"
    And OBSERVABILITY_SENDERS is "fine: {app: always}"
    When the evaluator runs at 10:30
    Then it succeeds
    And nothing is written to the tenant

  Scenario: Signals storage refuses fail the run
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And storage refuses writes
    When the evaluator runs at 10:30
    Then it fails with code 1
    And stderr mentions "the signals could not be written"

  Scenario: Without the signals not loaded yet, nothing is evaluated
    Given the signals tenant is OBSERVABILITY_STORAGE_URL
    And storage does not answer listings
    When the evaluator runs at 10:30
    Then it fails with code 2
    And stderr mentions "could not read the open signals"
