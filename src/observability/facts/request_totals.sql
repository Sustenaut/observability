-- fact: request_totals
-- version: 1
-- reads: calls
--
-- One row per app, plugin, operation and two-minute bucket of the timings a
-- service records for a whole request (operations service-total and
-- client-total): the same columns as plugin_rollups, kept apart from the calls
-- to outside services.
SELECT
  'request_totals' AS fact,
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
WHERE operation IN ('service-total', 'client-total')
GROUP BY app, plugin, operation, bucket
