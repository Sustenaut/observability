Feature: The observability command

  Scenario: It reports its version
    When I run observability with "--version"
    Then it succeeds
    And it prints "observability 0.1.0"

  Scenario: With no command it describes itself
    When I run observability with no arguments
    Then it succeeds
    And it prints "usage: observability"

  Scenario: It lists the facts with their versions
    When I run observability with "facts"
    Then it succeeds
    And it prints "sender_windows\tversion 1\treads status"
    And it prints "call_rollups\tversion 1\treads calls"

  Scenario: It prints a fact's query for the datasets configured
    Given OBSERVABILITY_DATASETS is "calls_example, calls_other"
    When I run observability with "facts sender_windows"
    Then it succeeds
    And it prints "FROM calls_example.status"
    And it prints "'other' AS project"

  Scenario: A dataset given on the command line wins
    Given OBSERVABILITY_DATASETS is "calls_example"
    When I run observability with "facts call_rollups --dataset calls_given"
    Then it succeeds
    And it prints "FROM calls_given.calls"

  Scenario: With no dataset it says how to give one
    When I run observability with "facts sender_windows"
    Then it fails with "no dataset: give --dataset or set OBSERVABILITY_DATASETS"

  Scenario: A name that is not a dataset's is refused
    When I run observability with "facts sender_windows --dataset 'x; DROP'"
    Then it fails with "'x; DROP' is not a BigQuery dataset name"

  Scenario: An unknown fact is named
    When I run observability with "facts nope --dataset calls_example"
    Then it fails with "no fact nope; there are call_rollups, sender_windows"
