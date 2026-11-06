-- fact: sender_windows
-- version: 2
-- reads: status
--
-- One row per sender and two-minute bucket. A sender is named by its prefix,
-- the pod or revision name with its generated suffix removed, since that
-- suffix changes with every pod and revision. Rows of one bucket, from one
-- sender reporting twice or from several pods of one prefix, are merged:
-- counts summed, the quickest and slowest answers kept, and the median a
-- count-weighted mean of the rows' medians, flagged approximate when more
-- than one row answered requests. A bucket with no row is a sender's
-- silence: this fact records what was reported, never what was not.
--
-- Version 2 reads only reports at or after {{since}}, a bucket's start, so a
-- rule reads its lookback alone and every bucket it reads is whole.
WITH reports AS (
  SELECT
    *,
    TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(`at`), 120) * 120) AS bucket,
    -- The suffixes: a Cloud Run revision's (plan-00012-abc), a Deployment
    -- pod's (app-7d9f8c6b5d-x2k4p), another generated pod name's
    -- (ingest-x2k4p) and a StatefulSet pod's (ingest-0). Kubernetes draws
    -- generated names from consonants and digits without 0, 1 and 3, so a
    -- word of the name itself, such as -proxy, is never taken for one.
    REGEXP_EXTRACT(
      sender,
      r'^(.+?)(?:-[0-9]{5}-[a-z0-9]{3}|-[bcdfghjklmnpqrstvwxz2456789]{6,10}-[bcdfghjklmnpqrstvwxz2456789]{5}|-[bcdfghjklmnpqrstvwxz2456789]{5}|-[0-9]+)?$'
    ) AS sender_prefix
  FROM {{dataset}}.status
  WHERE `at` >= {{since}}
)
SELECT
  'sender_windows' AS fact,
  '2' AS fact_version,
  '{{project}}' AS project,
  kind,
  sender_prefix,
  bucket,
  COUNT(*) AS reports,
  COUNT(DISTINCT sender) AS senders,
  MIN(cycle_start) AS first_cycle_start,
  MAX(cycle_end) AS last_cycle_end,
  -- Senders.
  SUM(calls) AS calls,
  SUM(drops) AS drops,
  SUM(storage_failures) AS storage_failures,
  MAX(buffer_size) AS peak_buffer,
  SUM(page_count) AS page_count,
  MIN(page_ms_low) AS page_ms_low,
  MAX(page_ms_high) AS page_ms_high,
  SAFE_DIVIDE(
    SUM(page_ms_median * page_count),
    SUM(IF(page_ms_median IS NULL, 0, page_count))
  ) AS page_ms_median,
  COUNTIF(page_count > 0 AND page_ms_median IS NOT NULL) > 1 AS page_ms_median_approximate,
  LOGICAL_OR(cold_start) AS cold_start,
  -- Ingest.
  LOGICAL_AND(storage_ok) AS storage_ok,
  SUM(loaded_files) AS loaded_files,
  SUM(rejected_now) AS rejected_now,
  MAX(inbox_files) AS waiting_files,
  MAX(inbox_bytes) AS waiting_bytes,
  LOGICAL_OR(inbox_more) AS waiting_more,
  MAX(inbox_oldest_seconds) AS waiting_oldest_seconds,
  MAX(rejected_files) AS rejected_files,
  LOGICAL_OR(rejected_more) AS rejected_more,
  MAX(rejected_oldest_seconds) AS rejected_oldest_seconds,
  MAX(jobs_today) AS jobs_today,
  MAX(status_jobs_today) AS status_jobs_today,
  STRING_AGG(DISTINCT problems, '; ' ORDER BY problems) AS problems
FROM reports
GROUP BY kind, sender_prefix, bucket
