Feature: The observability command

  Background:
    Given the program under test is "observability"
    And the environment does not set "OBSERVABILITY_DATASETS"

  Scenario: It reports its version
    When I run "observability --version"
    Then it succeeds
    And it prints "observability 0.1.0"

  Scenario: With no command it describes itself
    When I run "observability"
    Then it succeeds
    And it prints "usage: observability"

  Scenario: It lists the facts with their versions
    When I run "observability facts"
    Then it succeeds
    And it prints "sender_windows	version 2	reads status"
    And it prints "call_rollups	version 2	reads calls"
    And it prints "need_states	version 1	reads convergence.need_states"

  Scenario: It prints a fact's query for the datasets configured
    Given the environment sets "OBSERVABILITY_DATASETS" to "calls_example, calls_other"
    When I run "observability facts sender_windows"
    Then it succeeds
    And it prints "FROM calls_example.status"
    And it prints "'other' AS project"

  Scenario: A dataset given on the command line wins
    Given the environment sets "OBSERVABILITY_DATASETS" to "calls_example"
    When I run "observability facts call_rollups --dataset calls_given"
    Then it succeeds
    And it prints "FROM calls_given.calls"

  Scenario: With no dataset it says how to give one
    When I run "observability facts sender_windows"
    Then the exit code is 2
    And stderr mentions "observability: no dataset: give --dataset or set OBSERVABILITY_DATASETS"

  Scenario: A name that is not a dataset's is refused
    When I run "observability facts sender_windows --dataset 'x; DROP'"
    Then the exit code is 2
    And stderr mentions "observability: 'x; DROP' is not a BigQuery dataset name"

  Scenario: A fact that reads one table needs no dataset
    When I run "observability facts need_states"
    Then it succeeds
    And it prints "FROM convergence.need_states"

  Scenario: An unknown fact is named
    When I run "observability facts nope --dataset calls_example"
    Then the exit code is 2
    And stderr mentions "observability: no fact nope; there are call_rollups, need_states, pubrules_checks, sender_windows"

  Scenario: An empty OBSERVABILITY_THRESHOLDS passes the check
    Given the environment sets "OBSERVABILITY_THRESHOLDS" to "{version: 1, rules: {}}"
    When I run "observability thresholds --check"
    Then it succeeds
    And it prints "OBSERVABILITY_THRESHOLDS: no overrides, every rule as its file says"

  Scenario: A file holding the thresholds is checked instead
    Given a scratch directory
    And a file "thresholds.yaml" holding "{version: 1, rules: {sender_silent: {silent_minutes: 20}}}"
    When I run "observability thresholds --check thresholds.yaml"
    Then it succeeds
    And it prints "OBSERVABILITY_THRESHOLDS: overrides for sender_silent"

  Scenario: Thresholds the evaluator would refuse fail the check, saying why
    Given the environment sets "OBSERVABILITY_THRESHOLDS" to "{version: 1, rules: {sender_silent: {silent_minutes: 0}}}"
    When I run "observability thresholds --check"
    Then the exit code is 2
    And stderr mentions "observability: OBSERVABILITY_THRESHOLDS: sender_silent's silent_minutes is a finite number above 0, not 0"

  Scenario: A file that can't be read fails the check
    Given a scratch directory
    When I run "observability thresholds --check missing.yaml"
    Then the exit code is 2
    And stderr mentions "observability: missing.yaml can't be read"

  # integrations is pinned in four files, and CI builds no image: the
  # Dockerfile's lock (evaluator-requirements.in and .lock), pyproject.toml's
  # extra and tests/requirements.txt must name one wheel, or the deploy's
  # build is the first to find out.
  Scenario: The image, the package and the tests each pin one integrations wheel
    When the integrations wheels the requirements name are read
    Then the result is:
      | file                        | wheels |
      | evaluator-requirements.in   | 1      |
      | evaluator-requirements.lock | 1      |
      | pyproject.toml              | 1      |
      | tests/requirements.txt      | 1      |

  Scenario: The image, the package and the tests pin the same integrations wheel
    When the integrations wheels the requirements name are gathered
    Then the result has 1 wheel
