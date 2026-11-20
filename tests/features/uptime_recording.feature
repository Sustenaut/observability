Feature: The uptime probe records every result

  On Cloud Run, with UPTIME_TABLE set, each run appends one row per target to
  that BigQuery table, up or not, as the account attached to the job, whose
  token the metadata server gives. It keeps no state and posts nothing:
  observability's rules read the rows, and the notifier posts what they find.

  Background:
    Given a scratch directory
    And the environment sets "SUSTENAUT_SLACK_BOT_TOKEN" to "xoxb-test"
    And the environment sets "UPTIME_SLACK_CHANNEL" to "C0TEST"
    And the environment does not set "UPTIME_TARGETS"
    And the environment sets "UPTIME_TABLE" to "example.observability.uptime_probes"
    And the environment sets "CLOUD_RUN_EXECUTION" to "observability-uptime-abc12"
    And the "site" service answers "GET /ok" with 200
    And the "site" service answers "GET /broken" with 503
    And a fake "slack" service
    And the probe posts to the "slack" service's "/api/chat.postMessage"
    And the metadata server gives the token "ya29.test"
    And BigQuery takes every row

  Scenario: Every target is recorded, up or not, and a failing one fails the run
    Given the target "web" at "/ok"
    And the target "api" at "/broken"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And it prints "up	web	HTTP 200"
    And it prints "failing	api	HTTP 503, not 200"
    And it prints "uptime: recorded 2 targets in example.observability.uptime_probes"
    And stderr mentions "uptime: failing: api"
    And BigQuery was sent the rows:
      | insertId                       | target | up    | status | expect_status | attempts | detail             | execution                  |
      | observability-uptime-abc12/web | web    | true  | 200    | 200           | 1        | HTTP 200           | observability-uptime-abc12 |
      | observability-uptime-abc12/api | api    | false | 503    | 200           | 2        | HTTP 503, not 200  | observability-uptime-abc12 |
    And the "bigquery" service was asked "POST /projects/example/datasets/observability/tables/uptime_probes/insertAll" with the header "Authorization" set to "Bearer ya29.test"
    And the "metadata" service was asked "GET /token" with the header "Metadata-Flavor" set to "Google"
    And the "slack" service was asked nothing
    And the file "uptime-state.json" does not exist

  Scenario: Every target up is a run that succeeds
    Given the target "web" at "/ok"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And it prints "uptime: recorded 1 targets in example.observability.uptime_probes"

  Scenario: A target that doesn't answer is recorded with no status
    Given the target "web" at a port nothing listens on
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And BigQuery was sent the rows:
      | target | up    | status | attempts |
      | web    | false |        | 2        |

  Scenario: Off Cloud Run, a run names itself
    Given the target "web" at "/ok"
    And the environment does not set "CLOUD_RUN_EXECUTION"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And every row BigQuery was sent names an execution starting "local-"

  Scenario: Rows BigQuery refuses fail the run, with its reason
    Given the target "web" at "/ok"
    And BigQuery refuses every row as "invalid"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "recording to example.observability.uptime_probes failed: BigQuery refused 1 of 1 rows: invalid"

  Scenario: BigQuery not answering fails the run
    Given the target "web" at "/ok"
    And BigQuery answers every insert with 500
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "recording to example.observability.uptime_probes failed"

  Scenario: No token from the metadata server fails the run, and nothing is sent
    Given the target "web" at "/ok"
    And the metadata server gives no token
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "the metadata server gave no access token"
    And the "bigquery" service was asked nothing

  Scenario Outline: A bad UPTIME_TABLE is refused
    Given the target "web" at "/ok"
    And the environment sets "UPTIME_TABLE" to "<value>"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 2
    And stderr mentions "UPTIME_TABLE is project.dataset.table"
    And the "site" service was asked nothing

    Examples:
      | value                     |
      | observability.uptime      |
      | a.b.c.d                   |
      | example.observ ability.t  |
