Feature: Facts from the call log

  Each fact is a versioned BigQuery query over one project's call log
  dataset. Here each runs on fixture rows, locally.

  Scenario: Reports in one bucket merge into one window per sender prefix
    Given the dataset "calls_example" holds "split-window"
    When the fact "sender_windows" runs
    Then its rows are
      | sender_prefix | bucket | reports | senders | calls | drops | storage_failures | peak_buffer | page_count | page_ms_low | page_ms_high | page_ms_median | page_ms_median_approximate | cold_start |
      | app           | 10:00  | 3       | 2       | 6     | 1     | 1                | 9           | 40         | 20          | 900          | 175.0          | true                       | true       |
      | app           | 10:02  | 1       | 1       | 4     | 0     | 0                | 1           | 5          | 50          | 120          | 80.0           | false                      | false      |

  Scenario: A Cloud Run revision that goes silent leaves no windows, and its successor shares its prefix
    Given the dataset "calls_example" holds "silent-revision"
    When the fact "sender_windows" runs
    Then its rows are
      | sender_prefix | bucket | reports | calls | cold_start |
      | plan          | 10:00  | 1       | 1     | true       |
      | plan          | 10:02  | 1       | 1     | false      |
      | plan          | 10:04  | 1       | 0     | false      |
      | plan          | 10:20  | 1       | 2     | true       |

  Scenario: Ingest reports keep their own fields, apart from senders
    Given the dataset "calls_example" holds "ingest"
    When the fact "sender_windows" runs
    Then its rows are
      | kind   | sender_prefix | bucket | reports | calls | storage_ok | loaded_files | rejected_now | waiting_files | waiting_bytes | waiting_more | waiting_oldest_seconds | rejected_files | rejected_oldest_seconds | jobs_today | status_jobs_today | problems               |
      | ingest | ingest        | 10:00  | 2       |       | false      | 2            | 1            | 5             | 9000          | true         | 210                    | 2              | 3700                    | 41         | 42                | storage did not answer |
      | sender | ingest        | 10:00  | 1       | 7     |            |              |              |               |               |              |                        |                |                         |            |                   |                        |

  Scenario: Call rollups count calls, errors by outcome and latency, with request totals in their own scope
    Given the dataset "calls_example" holds "calls"
    When the fact "call_rollups" runs
    Then its rows are
      | scope         | app     | plugin         | operation     | bucket | calls | errors | refused | unavailable | retries | latency_ms_median | latency_ms_max |
      | plugin        | service | github.edit-pr | edit          | 10:00  | 5     | 2      | 1       | 1           | 2       | 200               | 900            |
      | plugin        | service | slack.post     | post          | 10:02  | 1     | 0      | 0       | 0           | 0       | 50                | 50             |
      | request_total | service | github.edit-pr | client-total  | 10:00  | 1     | 0      | 0       | 0           | 0       | 1500              | 1500           |
      | request_total | service | github.edit-pr | service-total | 10:00  | 1     | 0      | 0       | 0           | 0       | 1200              | 1200           |

  Scenario: Every row names its fact, version and project, across datasets
    Given the dataset "calls_example" holds "split-window"
    And the dataset "calls_other" holds "other-project"
    When the fact "sender_windows" runs
    Then its rows are
      | fact           | fact_version | project | sender_prefix | bucket |
      | sender_windows | 2            | example | app           | 10:00  |
      | sender_windows | 2            | example | app           | 10:02  |
      | sender_windows | 2            | other   | web           | 10:00  |

  Scenario: A fact file's header must name it
    When a fact file "windows" reads "-- fact: other\n-- version: 1\n-- reads: status\nSELECT 1"
    Then reading it fails with "windows.sql: its header names it other"

  Scenario: A fact file's header must give its version and table
    When a fact file "windows" reads "-- fact: windows\nSELECT 1"
    Then reading it fails with "windows.sql: its header has no reads, version"
