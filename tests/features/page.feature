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

  Scenario: A signal's page: its trend, the sender's windows, and its rule's other signals
    Given the open signal "drops" for "example/app" since 10:22, with evidence "project=example sender_prefix=app dropped=3"
    And the signal "drops" for "example/app" from 09:00 to 09:10
    When the page of "drops" for "example/app" since 10:22 is read at 10:30
    Then its trend is "10:00=0 10:28=3"
    And its context is "sender" with buckets "10:28 10:00"
    And its history is "10:22 open, 10:20 open, 09:00 09:10"

  Scenario: An app's calls to a plugin, around a plugin_errors signal
    Given the open signal "plugin_errors" for "example/service/github.edit-pr" since 10:20, with evidence "project=example app=service plugin=github.edit-pr"
    When the page of "plugin_errors" for "example/service/github.edit-pr" since 10:20 is read at 10:30
    Then its trend is "10:14=0 10:16=100"
    And its context is "plugin" with buckets "10:16 10:14"

  Scenario: The ingest pod's windows, around an ingest signal, and no trend for a rule without one
    Given the open signal "storage_unreachable" for "example" since 10:20, with evidence "project=example"
    When the page of "storage_unreachable" for "example" since 10:20 is read at 10:30
    Then its trend is ""
    And its context is "ingest" with buckets "10:28 10:20"

  Scenario: Evidence that names nothing around it shows no windows
    When the page of "drops" for "example/app" since 10:20 is read at 10:30
    Then its context is "" with buckets ""

  Scenario: The signal's page shows it, and the trends page links to it
    Given the open signal "drops" for "example/app" since 10:22, with evidence "project=example sender_prefix=app dropped=3"
    And the signal "drops" for "example/app" from 09:00 to 09:10
    When "/signals/drops/20261101T102200Z/example/app" is asked for
    Then it answers 200
    And it shows "drops: example/app"
    And it shows "A sender dropped call records in the last 6 minutes."
    And it shows "<svg"
    And it shows "threshold 0"
    And it shows "Windows of the sender"
    And it shows "this one"
    And it shows "/signals/drops/20261101T090000Z/example/app"
    And it is never cached and runs no script
    When the page is asked for
    Then it shows "<a href="/signals/drops/20261101T102000Z/example/app">example/app</a>"

  Scenario: An ended signal's page says how long it lasted, and a trend with nothing in it says so
    Given the signal "slow_pages" for "example/web" from 10:00 to 10:12
    When "/signals/slow_pages/20261101T100000Z/example/web" is asked for
    Then it answers 200
    And it shows "after 12 min"
    And it shows "No slowest warm answer, ms in this window."

  Scenario: A rule with no trend says so
    Given the open signal "storage_unreachable" for "example" since 10:20, with evidence "project=example"
    When "/signals/storage_unreachable/20261101T102000Z/example" is asked for
    Then it shows "This rule has no trend to chart yet."
    And it shows "Windows of the ingest pod"

  Scenario: A subject on a signal's page is shown, never run
    Given the open signal "drops" for "<b>x</b>" since 10:20
    When "/signals/drops/20261101T102000Z/%3Cb%3Ex%3C/b%3E" is asked for
    Then it answers 200
    And it shows "&lt;b&gt;x&lt;/b&gt;"

  Scenario Outline: An address that names no signal is a 404
    When "<path>" is asked for
    Then it answers 404

    Examples:
      | path                                            |
      | /signals/drops/20261101T102000Z/example/other    |
      | /signals/drops/20261101T102001Z/example/app      |
      | /signals/no_rule/20261101T102000Z/example/app    |
      | /signals/Drops/20261101T102000Z/example/app      |
      | /signals/drops/2026-11-01T10:20/example/app      |
      | /signals/drops/20261341T102000Z/example/app      |

  Scenario: A signal's page needs BigQuery, and without the loader there are no signal pages
    Given BigQuery doesn't answer
    When "/signals/drops/20261101T102000Z/example/app" is asked for
    Then it answers 503
    And an app with no signal loader answers 404 for "/signals/drops/20261101T102000Z/example/app"

  Scenario Outline: The address of a signal's page
    Then the path of "<rule>" for "<subject>" since "<started>" is "<path>"

    Examples:
      | rule  | subject       | started                          | path                                                  |
      | drops | example/app   | 2026-11-01T10:20:00+00:00        | /signals/drops/20261101T102000Z/example/app            |
      | drops | a b?c         | 2026-11-01T10:20:00.000250+00:00 | /signals/drops/20261101T102000.000250Z/a%20b%3Fc       |
      | drops | example       | 2026-11-01T12:20:00+02:00        | /signals/drops/20261101T102000Z/example                |
      | drops | example       | 2026-11-01T10:20:00              | /signals/drops/20261101T102000Z/example                |

  Scenario: Every address reads back as the moment it was made from, and a bad rule id has none
    Then "20261101T102000.000250Z" reads back as "2026-11-01T10:20:00.000250+00:00"
    And the full address of "drops" for "example/app" since "2026-11-01T10:20:00+00:00" is "https://observability.sustenaut.eu/signals/drops/20261101T102000Z/example/app"
    And a rule id "Not one" has no address
