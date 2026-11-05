Feature: The observability command

  Scenario: It reports its version
    When I run observability with "--version"
    Then it succeeds
    And it prints "observability 0.1.0"

  Scenario: With no command it describes itself
    When I run observability with no arguments
    Then it succeeds
    And it prints "usage: observability"
