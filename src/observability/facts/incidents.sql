-- fact: incidents
-- version: 1
-- reads: observability.incidents_view
--
-- One row per notification Cloud Monitoring sent of an SLA incident: shared-infra's
-- sla-monitoring.tf sends each one, opened and closed, through Pub/Sub into
-- observability.incidents, which incidents_view reads out. An incident that has closed
-- has a row of each state. service, sender, tier and kind are its policy's labels, as
-- sla-monitoring.tf sets them on every SLA policy; sender is "none" on uptime's.
SELECT
  'incidents' AS fact,
  '1' AS fact_version,
  incident_id,
  state,
  policy_name,
  started_at,
  ended_at,
  summary,
  severity,
  condition_name,
  url,
  service,
  sender,
  tier,
  kind,
  publish_time
FROM observability.incidents_view
WHERE publish_time >= {{since}}
