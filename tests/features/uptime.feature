Feature: The uptime probe

  Each target is a URL and the status it should answer with. The probe
  runs from outside the server it watches, keeps its state between runs,
  and calls a target down only after two runs in a row have failed.

  Background:
    Given a scratch directory
    And the environment sets "SUSTENAUT_SLACK_BOT_TOKEN" to "xoxb-test"
    And the environment sets "UPTIME_SLACK_CHANNEL" to "C0TEST"
    And the environment does not set "UPTIME_TARGETS"
    And the "site" service answers "GET /ok" with 200
    And the "site" service answers "GET /broken" with 503
    And the "site" service answers "GET /moved" with 302 and the header "Location" set to "/ok"
    And a fake "slack" service
    And the probe posts to the "slack" service's "/api/chat.postMessage"

  Scenario: Every target answers
    Given the target "web" at "/ok"
    And the target "api" at "/ok"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And it prints "up	web	HTTP 200"
    And it prints "up	api	HTTP 200"
    And the JSON in "uptime-state.json" has "web" equal to "{"failures": 0, "down": false}"
    And the "slack" service was asked nothing

  Scenario: One failed run is not yet down
    Given the target "web" at "/broken"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And it prints "failing	web	HTTP 503, not 200"
    And the JSON in "uptime-state.json" has "web" equal to "{"failures": 1, "down": false}"
    And the "slack" service was asked nothing

  Scenario: A second failed run in a row is down, and says so in Slack
    Given the target "web" at "/broken"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 1, "down": false}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {"ok": true}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And it prints "DOWN	web	HTTP 503, not 200"
    And stderr mentions "uptime: down: web"
    And Slack was told "web is down: HTTP 503, not 200" in "C0TEST"
    And the "slack" service was asked "POST /api/chat.postMessage" with the header "Authorization" set to "Bearer xoxb-test"

  Scenario: A target still down is not announced again, and the run still fails
    Given the target "web" at "/broken"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 4, "down": true}}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And the "slack" service was asked nothing

  Scenario: A target down that answers again has recovered
    Given the target "web" at "/ok"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 3, "down": true}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {"ok": true}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And Slack was told "web has recovered: HTTP 200" in "C0TEST"
    And the "slack" service was asked "POST /api/chat.postMessage" with the header "Authorization" set to "Bearer xoxb-test"
    And the JSON in "uptime-state.json" has "web" equal to "{"failures": 0, "down": false}"

  Scenario: A redirect is the answer, not a page to follow
    Given the target "gate" at "/moved" expecting 302
    And the target "page" at "/moved"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it prints "up	gate	HTTP 302"
    And it prints "failing	page	HTTP 302, not 200"

  Scenario: A target that fails once and then answers is up
    Given the "site" service answers "GET /flaky" with 503
    And the "site" service answers "GET /flaky" with 200
    And the target "web" at "/flaky"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And it prints "up	web	HTTP 200"
    And the "site" service was asked "GET /flaky" 2 times

  Scenario: A server that does not answer in time is failing
    Given the target "web" at a port that takes the request and never answers
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it prints "failing	web	no answer"

  Scenario: A server that refuses the connection is failing
    Given the target "web" at a port nothing listens on
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it prints "failing	web	no answer"

  Scenario: Without the bot's token it says so, and the run still fails
    Given the target "web" at "/broken"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 1, "down": false}}
      """
    And the environment does not set "SUSTENAUT_SLACK_BOT_TOKEN"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "no SUSTENAUT_SLACK_BOT_TOKEN, so nothing was posted to Slack"
    And the "slack" service was asked nothing

  Scenario: Each target alerts its own channel, and the rest the default, one post per channel
    Given the target "web" at "/broken" alerting "C0WEB"
    And the target "api" at "/broken"
    And the target "db" at "/broken"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 1, "down": false}, "api": {"failures": 1, "down": false}, "db": {"failures": 1, "down": false}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {"ok": true}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And Slack was told "web is down" in "C0WEB"
    And Slack was told "api is down" in "C0TEST"
    And Slack was told "db is down" in "C0TEST"
    And the "slack" service was asked "POST /api/chat.postMessage" 2 times
    And the "slack" service was asked "POST /api/chat.postMessage" with the header "Authorization" set to "Bearer xoxb-test"

  Scenario: Without a default channel only the targets with their own are posted
    Given the target "web" at "/broken" alerting "C0WEB"
    And the target "api" at "/broken"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 1, "down": false}, "api": {"failures": 1, "down": false}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {"ok": true}
      """
    And the environment does not set "UPTIME_SLACK_CHANNEL"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And Slack was told "web is down" in "C0WEB"
    And the "slack" service was asked "POST /api/chat.postMessage" 1 times
    And the "slack" service was asked "POST /api/chat.postMessage" with the header "Authorization" set to "Bearer xoxb-test"
    And stderr mentions "no UPTIME_SLACK_CHANNEL, and no channel of their own, for api, so nothing was posted for them"

  Scenario: A post Slack refuses fails the run, with Slack's reason
    Given the target "web" at "/ok"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 2, "down": true}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {"ok": false, "error": "not_in_channel"}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "posting to Slack failed, for C0TEST: Slack refused the post: not_in_channel"

  Scenario: A refusal without a reason still fails the run
    Given the target "web" at "/ok"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 2, "down": true}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 200 and:
      """
      {}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "Slack refused the post: no reason given"

  Scenario: Slack not answering fails the run
    Given the target "web" at "/ok"
    And a file "uptime-state.json" holding:
      """
      {"web": {"failures": 2, "down": true}}
      """
    And the "slack" service answers "POST /api/chat.postMessage" with 500
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 1
    And stderr mentions "posting to Slack failed"

  Scenario: An unreadable state is a first run
    Given the target "web" at "/broken"
    And a file "uptime-state.json" holding "not json"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And the JSON in "uptime-state.json" has "web" equal to "{"failures": 1, "down": false}"

  Scenario: A state that is not an object is a first run
    Given the target "web" at "/broken"
    And a file "uptime-state.json" holding "[1, 2]"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And the JSON in "uptime-state.json" has "web" equal to "{"failures": 1, "down": false}"

  Scenario: A target no longer listed is forgotten
    Given the target "web" at "/ok"
    And a file "uptime-state.json" holding:
      """
      {"old": {"failures": 5, "down": true}}
      """
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then it succeeds
    And the JSON in "uptime-state.json" is:
      """
      {"web": {"failures": 0, "down": false}}
      """

  Scenario Outline: A bad UPTIME_TARGETS is refused
    Given the environment sets "UPTIME_TARGETS" to "<value>"
    When I run "python3 -m observability.uptime --timeout 0.5 --pause 0"
    Then the exit code is 2
    And stderr mentions "<message>"

    Examples:
      | value                                                                         | message                                          |
      | not json                                                                      | UPTIME_TARGETS is not JSON                        |
      | []                                                                            | UPTIME_TARGETS must be a JSON list of targets     |
      | [{"name": "a", "url": "https://a.test", "port": 1}]                           | each target is                                    |
      | [{"name": "a", "url": "ftp://a.test"}]                                        | a target needs a name and an http(s) url          |
      | [{"name": "a", "url": "https://a.test", "expect_status": 99}]                 | a's expect_status must be an HTTP status          |
      | [{"name": "a", "url": "https://a.test", "channel": " "}]                      | a's channel must be a channel's or a person's id  |
      | [{"name": "a", "url": "https://a.test", "channel": 7}]                        | a's channel must be a channel's or a person's id  |
      | [{"name": "a", "url": "https://a.test"}, {"name": "a", "url": "https://b.test"}] | UPTIME_TARGETS names a target twice            |
