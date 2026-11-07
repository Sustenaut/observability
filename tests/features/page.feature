Feature: The trends page

  observability.sustenaut.eu/trends/integrations shows the last day of the
  facts and the signals, behind the team sign-in. Here its queries run on
  fixture rows at 10:30, locally.

  Background:
    Given the dataset "calls_example" holds "unhealthy"
    And the senders are "example: {app: always, web: always, plan: on-demand, missing: always}"
    And the open signal "drops" for "example/app" since 10:20
    And the signal "storage_unreachable" for "example" from 09:00 to 09:30

  Scenario: Calls by plugin, with errors and latency, and no request totals
    When the page's trends are read at 10:30
    Then the plugins are
      | project | app     | plugin         | operation | call_count | error_count | refused_count | unavailable_count | typical_ms | slowest_ms |
      | example | service | github.edit-pr | edit      | 25         | 3           | 0             | 3                 | 196        | 900        |
      | example | service | slack.post     | post      | 25         | 1           | 1             | 0                 | 50         | 50         |

  Scenario: Every sender seen or expected, and which are silent
    When the page's trends are read at 10:30
    Then the senders are
      | project | kind   | prefix  | expected  | last_seen | windows_last_hour | silent |
      | example | ingest | ingest  |           | 10:28     | 2                 | false  |
      | example | sender | app     | always    | 10:28     | 2                 | false  |
      | example | sender | missing | always    |           | 0                 | true   |
      | example | sender | plan    | on-demand | 10:00     | 1                 | false  |
      | example | sender | web     | always    | 10:10     | 1                 | true   |

  Scenario: Page times by window, newest first, with cold starts marked
    When the page's trends are read at 10:30
    Then the page times of "example/app" are
      | bucket | page_count | page_ms_high | cold_start |
      | 10:28  | 10         | 7000         | false      |
      | 10:00  | 5          | 100          | true       |

  Scenario: Open signals, and those ended in the last day
    When the page's trends are read at 10:30
    Then the open signals are "drops example/app"
    And the recent signals are "storage_unreachable example"

  Scenario: The page shows them all
    When the page is asked for
    Then it answers 200
    And it shows "Integrations: trends"
    And it shows "github.edit-pr"
    And it shows "silent"
    And it shows "cold start"
    And it shows "dropped: 3"
    And it shows "storage_unreachable"
    And it is never cached and runs no script

  Scenario: What a subject says is shown, never run
    Given the open signal "drops" for "<b>example</b>" since 10:20
    When the page is asked for
    Then it shows "&lt;b&gt;example&lt;/b&gt;"

  Scenario: With nothing to show, it says so
    Given no dataset and no senders
    When the page is asked for
    Then it shows "No calls in the last day."
    And it shows "No sender has reported in the last day."
    And it shows "No sender answered requests in the last day."

  Scenario: BigQuery not answering is a 503
    Given BigQuery doesn't answer
    When the page is asked for
    Then it answers 503

  Scenario: The site's root and the page's own path lead to the page, and health needs nothing
    Then "/" leads to "/trends/integrations/"
    And "/trends/integrations" leads to "/trends/integrations/"
    And "/healthz" answers ok
    And what uvicorn runs imports, with no app until it has its key
