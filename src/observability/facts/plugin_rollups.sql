-- fact: plugin_rollups
-- version: 1
-- reads: calls
--
-- One row per app, plugin, operation and two-minute bucket of the calls an app
-- made: how many, how many failed (refused or unavailable), and how long they
-- took. A service's own timing of a whole request (operations service-total
-- and client-total) is not a call to an outside service, so it is left out
-- here and kept in request_totals.
SELECT
  'plugin_rollups' AS fact,
  '1' AS fact_version,
  '{{project}}' AS project,
  app,
  plugin,
  operation,
  TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(`at`), 120) * 120) AS bucket,
  COUNT(*) AS calls,
  COUNTIF(outcome != 'ok') AS errors,
  COUNTIF(outcome = 'refused') AS refused,
  COUNTIF(outcome = 'unavailable') AS unavailable,
  SUM(retries) AS retries,
  APPROX_QUANTILES(latency_ms, 2)[OFFSET(1)] AS latency_ms_median,
  MAX(latency_ms) AS latency_ms_max
FROM {{dataset}}.calls
WHERE operation NOT IN ('service-total', 'client-total')
GROUP BY app, plugin, operation, bucket
