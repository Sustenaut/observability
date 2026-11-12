-- fact: need_states
-- version: 1
-- reads: convergence.need_states
--
-- One row per need per walk, as the convergence engine found it: every
-- deploy service's needs, walked read-only every 30 minutes, and by a person
-- from a laptop or the engine's page. The engine writes what it found, never
-- that something is wrong; the integrations ingest pod loads its buffer
-- (storage's need-states tenant) into this table. A need is named by its
-- repository, unit and id, which stay the same from walk to walk.
SELECT
  'need_states' AS fact,
  '1' AS fact_version,
  observed_at,
  repository,
  unit,
  need,
  type,
  name,
  grade,
  state,
  walked_from,
  walk_started_at
FROM convergence.need_states
-- By when each need was checked: the table is partitioned on it.
WHERE observed_at >= {{since}}
