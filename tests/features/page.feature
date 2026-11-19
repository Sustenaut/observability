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
    When the page's plugins are read at 10:30
    Then the result is:
      | project | app     | plugin         | operation | call_count | error_count | refused_count | unavailable_count | typical_ms | slowest_ms |
      | example | service | github.edit-pr | edit      | 25         | 3           | 0             | 3                 | 196        | 900        |
      | example | service | slack.post     | post      | 25         | 1           | 1             | 0                 | 50         | 50         |

  Scenario: Every sender seen or expected, and which are silent
    When the page's senders are read at 10:30
    Then the result is:
      | project | kind   | prefix  | expected  | last_seen | windows_last_hour | silent |
      | example | ingest | ingest  |           | 10:28     | 2                 | false  |
      | example | sender | app     | always    | 10:28     | 2                 | false  |
      | example | sender | missing | always    |           | 0                 | true   |
      | example | sender | plan    | on-demand | 10:00     | 1                 | false  |
      | example | sender | web     | always    | 10:10     | 1                 | true   |

  Scenario: Page times by window, newest first, with cold starts marked
    When the page times of "example/app" are read at 10:30
    Then the result is:
      | bucket | page_count | page_ms_high | cold_start |
      | 10:28  | 10         | 7000         | false      |
      | 10:00  | 5          | 100          | true       |

  Scenario: Open signals, and those ended in the last day
    When the page's signals are read at 10:30
    Then the result's "open" is "["drops example/app"]"
    And the result's "recent" is "["storage_unreachable example"]"

  Scenario: The page shows them all
    When I GET "/trends/integrations/"
    Then the answer is 200
    And the answer includes "Integrations: trends"
    And the answer includes "github.edit-pr"
    And the answer includes "silent"
    And the answer includes "cold start"
    And the answer includes "dropped: 3"
    And the answer includes "storage_unreachable"
    And the answer's "Cache-Control" is "private, no-store"
    And the answer's "Content-Security-Policy" is "default-src 'none'; style-src 'unsafe-inline'"
    And the answer does not include "<script"

  Scenario: What a subject says is shown, never run
    Given the open signal "drops" for "<b>example</b>" since 10:20
    When I GET "/trends/integrations/"
    Then the answer includes "&lt;b&gt;example&lt;/b&gt;"

  Scenario: With nothing to show, it says so
    Given no dataset and no senders
    When I GET "/trends/integrations/"
    Then the answer includes "No calls in the last day."
    And the answer includes "No sender has reported in the last day."
    And the answer includes "No sender answered requests in the last day."

  Scenario: BigQuery not answering is a 503
    Given BigQuery doesn't answer
    When I GET "/trends/integrations/"
    Then the answer is 503

  Scenario Outline: The site's root and the page's own path lead to the page
    When I GET "<path>"
    Then the answer is 307
    And the answer redirects to "/trends/integrations/"

    Examples:
      | path                 |
      | /                    |
      | /trends/integrations |

  Scenario: Health needs nothing
    Given BigQuery doesn't answer
    When I GET "/healthz"
    Then the answer is 200
    And the answer is the JSON:
      """
      {"status": "ok"}
      """

  Scenario: What uvicorn runs imports, with no app until it has its key
    Given the environment does not set "OBSERVABILITY_GOOGLE_CREDENTIAL_FILE"
    When what uvicorn runs is imported
    Then the result is empty

  Scenario: A signal's page: its trend, the sender's windows, and its rule's other signals
    Given the open signal "drops" for "example/app" since 10:22, with evidence "project=example sender_prefix=app dropped=3"
    And the signal "drops" for "example/app" from 09:00 to 09:10
    When the page of "drops" for "example/app" since 10:22 is read at 10:30
    Then the result's "trend" is "10:00=0 10:28=3"
    And the result's "context" is "sender"
    And the result's "buckets" is "10:28 10:00"
    And the result's "history" is "10:22 open, 10:20 open, 09:00 09:10"

  Scenario: An app's calls to a plugin, around a plugin_errors signal
    Given the open signal "plugin_errors" for "example/service/github.edit-pr" since 10:20, with evidence "project=example app=service plugin=github.edit-pr"
    When the page of "plugin_errors" for "example/service/github.edit-pr" since 10:20 is read at 10:30
    Then the result's "trend" is "10:14=0 10:16=100"
    And the result's "context" is "plugin"
    And the result's "buckets" is "10:16 10:14"

  Scenario: The ingest pod's windows, around an ingest signal, and no trend for a rule without one
    Given the open signal "storage_unreachable" for "example" since 10:20, with evidence "project=example"
    When the page of "storage_unreachable" for "example" since 10:20 is read at 10:30
    Then the result is:
      """
      {"trend": "", "context": "ingest", "buckets": "10:28 10:20", "history": "10:20 open, 09:00 09:30"}
      """

  Scenario: Evidence that names nothing around it shows no windows
    When the page of "drops" for "example/app" since 10:20 is read at 10:30
    Then the result is:
      """
      {"trend": "10:00=0 10:28=3", "context": "", "buckets": "", "history": "10:20 open"}
      """

  Scenario: The signal's page shows it, and the trends page links to it
    Given the open signal "drops" for "example/app" since 10:22, with evidence "project=example sender_prefix=app dropped=3"
    And the signal "drops" for "example/app" from 09:00 to 09:10
    When I GET "/signals/drops/20261101T102200Z/example/app"
    Then the answer is 200
    And the answer includes "drops: example/app"
    And the answer includes "A sender dropped call records in the last 6 minutes."
    And the answer includes "<svg"
    And the answer includes "threshold 0"
    And the answer includes "Windows of the sender"
    And the answer includes "this one"
    And the answer includes "/signals/drops/20261101T090000Z/example/app"
    And the answer's "Cache-Control" is "private, no-store"
    And the answer's "Content-Security-Policy" is "default-src 'none'; style-src 'unsafe-inline'"
    And the answer does not include "<script"
    When I GET "/trends/integrations/"
    Then the answer includes "<a href="/signals/drops/20261101T102000Z/example/app">example/app</a>"

  Scenario: An ended signal's page says how long it lasted, and a trend with nothing in it says so
    Given the signal "slow_pages" for "example/web" from 10:00 to 10:12
    When I GET "/signals/slow_pages/20261101T100000Z/example/web"
    Then the answer is 200
    And the answer includes "after 12 min"
    And the answer includes "No slowest warm answer, ms in this window."

  Scenario: A rule with no trend says so
    Given the open signal "storage_unreachable" for "example" since 10:20, with evidence "project=example"
    When I GET "/signals/storage_unreachable/20261101T102000Z/example"
    Then the answer includes "This rule has no trend to chart yet."
    And the answer includes "Windows of the ingest pod"

  Scenario: A subject on a signal's page is shown, never run
    Given the open signal "drops" for "<b>x</b>" since 10:20
    When I GET "/signals/drops/20261101T102000Z/%3Cb%3Ex%3C/b%3E"
    Then the answer is 200
    And the answer includes "&lt;b&gt;x&lt;/b&gt;"

  Scenario Outline: An address that names no signal is a 404
    When I GET "<path>"
    Then the answer is 404

    Examples:
      | path                                            |
      | /signals/drops/20261101T102000Z/example/other    |
      | /signals/drops/20261101T102001Z/example/app      |
      | /signals/no_rule/20261101T102000Z/example/app    |
      | /signals/Drops/20261101T102000Z/example/app      |
      | /signals/drops/2026-11-01T10:20/example/app      |
      | /signals/drops/20261341T102000Z/example/app      |

  Scenario: A signal's page needs BigQuery
    Given BigQuery doesn't answer
    When I GET "/signals/drops/20261101T102000Z/example/app"
    Then the answer is 503

  Scenario: Without the signal loader there are no signal pages
    Given an app with no signal loader
    When I GET "/signals/drops/20261101T102000Z/example/app"
    Then the answer is 404

  Scenario Outline: The address of a signal's page
    When the path of "<rule>" for "<subject>" since "<started>" is made
    Then the result is "<path>"

    Examples:
      | rule  | subject       | started                          | path                                                  |
      | drops | example/app   | 2026-11-01T10:20:00+00:00        | /signals/drops/20261101T102000Z/example/app            |
      | drops | a b?c         | 2026-11-01T10:20:00.000250+00:00 | /signals/drops/20261101T102000.000250Z/a%20b%3Fc       |
      | drops | example       | 2026-11-01T12:20:00+02:00        | /signals/drops/20261101T102000Z/example                |
      | drops | example       | 2026-11-01T10:20:00              | /signals/drops/20261101T102000Z/example                |

  Scenario: An address reads back as the moment it was made from
    When the moment "20261101T102000.000250Z" names is read
    Then the result is "2026-11-01T10:20:00.000250+00:00"

  Scenario: A moment is written as the address names it
    When the address of "2026-11-01T10:20:00.000250+00:00" is written
    Then the result is "20261101T102000.000250Z"

  Scenario: A signal's full address is on the site
    When the full address of "drops" for "example/app" since "2026-11-01T10:20:00+00:00" is made
    Then the result is "https://observability.sustenaut.eu/signals/drops/20261101T102000Z/example/app"

  Scenario: A bad rule id has no address
    When the path of "Not one" for "x" since "2026-11-01T10:30:00+00:00" is made
    Then it is refused, saying "not a rule id: 'Not one'"
