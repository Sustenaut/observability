-- fact: uptime_probes
-- version: 1
-- reads: observability.uptime_probes
--
-- One row per target per run of the uptime probe, up or not: the Cloud Run job
-- observability-uptime, which Cloud Scheduler starts every five minutes off the k3s
-- server, appends them itself, streamed in as an account that may only append, so the
-- table is the record of every site's answers. A target is named by its name in
-- UPTIME_TARGETS; one run's rows share its execution.
SELECT
  'uptime_probes' AS fact,
  '1' AS fact_version,
  probed_at,
  execution,
  target,
  url,
  up,
  status,
  expect_status,
  detail,
  attempts,
  elapsed_ms
FROM observability.uptime_probes
-- By when each target was probed: the table is partitioned on it.
WHERE probed_at >= {{since}}
