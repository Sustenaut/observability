-- fact: pubkit_checks
-- version: 1
-- reads: platform.pubkit_checks
--
-- One row per repository per check per night, as release-controlplane's nightly found
-- it: every repository on the release board, its pin (the pubkit it pins against pubkit's
-- latest release) and its sync (main's latest pubkit sync --check), passes as well as
-- failures. The nightly writes what it found, never that something is wrong; the
-- integrations ingest pod loads its buffer (storage's pubkit-checks tenant) into this
-- table, which is only ever appended to. A check is named by its repository and check,
-- which stay the same from night to night.
SELECT
  'pubkit_checks' AS fact,
  '1' AS fact_version,
  observed_at,
  repository,
  `check`,
  status,
  pinned,
  latest,
  main_commit,
  run_url,
  fix,
  run_started_at
FROM platform.pubkit_checks
-- By when each repository was checked: the table is partitioned on it.
WHERE observed_at >= {{since}}
