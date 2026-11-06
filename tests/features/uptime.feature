Feature: The uptime probe

  Each target is a URL and the status it should answer with. The probe
  runs from outside the server it watches, keeps its state between runs,
  and calls a target down only after two runs in a row have failed.

  Background:
    Given a site that answers "/ok" with 200, "/broken" with 503 and "/moved" with a redirect

  Scenario: Every target answers
    Given the targets "web" at "/ok" and "api" at "/ok"
    When the probe runs
    Then it succeeds
    And it prints "up\tweb\tHTTP 200"
    And the state says "web" has 0 failures and is up
    And nothing was posted to Slack

  Scenario: One failed run is not yet down
    Given the target "web" at "/broken"
    When the probe runs
    Then it succeeds
    And it prints "failing\tweb\tHTTP 503, not 200"
    And the state says "web" has 1 failures and is up
    And nothing was posted to Slack

  Scenario: A second failed run in a row is down, and says so in Slack
    Given the target "web" at "/broken"
    And the last run left "web" with 1 failures, up
    When the probe runs
    Then it fails
    And it prints "DOWN\tweb\tHTTP 503, not 200"
    And stderr mentions "uptime: down: web"
    And Slack was told "web is down: HTTP 503, not 200"

  Scenario: A target still down is not announced again, and the run still fails
    Given the target "web" at "/broken"
    And the last run left "web" with 4 failures, down
    When the probe runs
    Then it fails
    And nothing was posted to Slack

  Scenario: A target down that answers again has recovered
    Given the target "web" at "/ok"
    And the last run left "web" with 3 failures, down
    When the probe runs
    Then it succeeds
    And Slack was told "web has recovered: HTTP 200"
    And the state says "web" has 0 failures and is up

  Scenario: A redirect is the answer, not a page to follow
    Given the target "gate" at "/moved" expecting 302
    And the target "page" at "/moved"
    When the probe runs
    Then it prints "up\tgate\tHTTP 302"
    And it prints "failing\tpage\tHTTP 302, not 200"

  Scenario: A target that fails once and then answers is up
    Given the target "web" at "/flaky"
    When the probe runs
    Then it prints "up\tweb\tHTTP 200"

  Scenario: A server that does not answer in time is failing
    Given the target "web" at "/slow"
    When the probe runs
    Then it prints "failing\tweb\tno answer"

  Scenario: A server that refuses the connection is failing
    Given the target "web" at a port nothing listens on
    When the probe runs
    Then it prints "failing\tweb\tno answer"

  Scenario: Without a webhook it says so, and the run still fails
    Given the target "web" at "/broken"
    And the last run left "web" with 1 failures, up
    And no Slack webhook
    When the probe runs
    Then it fails
    And stderr mentions "no UPTIME_SLACK_WEBHOOK, so nothing was posted to Slack"

  Scenario: A webhook that refuses the post fails the run
    Given the target "web" at "/ok"
    And the last run left "web" with 2 failures, down
    And a Slack webhook that answers 500
    When the probe runs
    Then it fails
    And stderr mentions "posting to Slack failed"

  Scenario: An unreadable state is a first run
    Given the target "web" at "/broken"
    And the state file reads "not json"
    When the probe runs
    Then it succeeds
    And the state says "web" has 1 failures and is up

  Scenario: A state that is not an object is a first run
    Given the target "web" at "/broken"
    And the state file reads "[1, 2]"
    When the probe runs
    Then the state says "web" has 1 failures and is up

  Scenario: A target no longer listed is forgotten
    Given the target "web" at "/ok"
    And the last run left "old" with 5 failures, down
    When the probe runs
    Then it succeeds
    And the state names only "web"

  Scenario Outline: A bad UPTIME_TARGETS is refused
    Given UPTIME_TARGETS is '<value>'
    When the probe runs
    Then it exits with 2
    And stderr mentions "<message>"

    Examples:
      | value                                                                         | message                                          |
      | not json                                                                      | UPTIME_TARGETS is not JSON                        |
      | []                                                                            | UPTIME_TARGETS must be a JSON list of targets     |
      | [{"name": "a", "url": "https://a.test", "port": 1}]                           | each target is                                    |
      | [{"name": "a", "url": "ftp://a.test"}]                                        | a target needs a name and an http(s) url          |
      | [{"name": "a", "url": "https://a.test", "expect_status": 99}]                 | a's expect_status must be an HTTP status          |
      | [{"name": "a", "url": "https://a.test"}, {"name": "a", "url": "https://b.test"}] | UPTIME_TARGETS names a target twice            |
