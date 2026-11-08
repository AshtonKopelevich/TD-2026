CREATE TABLE marts.mart_tickets AS
WITH context AS (
 SELECT o.operation_id,
 coalesce(sum(d.available_seconds/3600.0) FILTER(WHERE d.gaming_date<o.gaming_date),0)::DOUBLE AS before_available_hours,
 coalesce(sum(d.available_seconds/3600.0) FILTER(WHERE d.gaming_date>o.restored_gaming_date),0)::DOUBLE AS after_available_hours,
 coalesce(sum(d.theo_usd) FILTER(WHERE d.gaming_date<o.gaming_date),0)::DECIMAL(28,8) AS before_theo_usd,
 coalesce(sum(d.theo_usd) FILTER(WHERE d.gaming_date>o.restored_gaming_date),0)::DECIMAL(28,8) AS after_theo_usd,
 count(d.gaming_date) FILTER(WHERE d.gaming_date<o.gaming_date)::BIGINT AS before_days,
 count(d.gaming_date) FILTER(WHERE d.gaming_date>o.restored_gaming_date)::BIGINT AS after_days,
 count(DISTINCT d.location_id)>1 OR count(DISTINCT d.config_id)>1 AS context_changed,
 count(f.machine_id)>0 AS overlapping_faults
 FROM staging.operation_intervals o LEFT JOIN marts.mart_machine_daily d ON d.machine_id=o.machine_id AND
  ((d.gaming_date>=o.gaming_date-INTERVAL '{{context_days}} days' AND d.gaming_date<o.gaming_date)
   OR (d.gaming_date>o.restored_gaming_date AND d.gaming_date<=o.restored_gaming_date+INTERVAL '{{context_days}} days'))
 LEFT JOIN staging.fault_days f ON f.machine_id=d.machine_id AND f.gaming_date=d.gaming_date
 GROUP BY o.operation_id
), base AS (
 SELECT o.operation_id,o.machine_id,o.location_id,o.event_type,o.event_type='fault_repair' AS controllable_fault,
 o.gaming_date,o.opened_at_utc,o.recorded_at_utc,o.work_started_at_utc,o.available_at_utc,
 date_diff('microsecond',o.opened_at_utc,o.work_started_at_utc)/3600000000.0 AS response_hours,
 date_diff('microsecond',o.work_started_at_utc,o.available_at_utc)/3600000000.0 AS repair_hours,
 date_diff('microsecond',o.opened_at_utc,o.available_at_utc)/3600000000.0 AS total_outage_hours,
 (o.direct_cost_cents*0.01)::DECIMAL(24,2) AS direct_cost_usd,c.* EXCLUDE(operation_id),
 before_theo_usd::DOUBLE/nullif(before_available_hours,0) AS before_theo_per_hour,
 after_theo_usd::DOUBLE/nullif(after_available_hours,0) AS after_theo_per_hour,
 before_days<{{context_days}} OR after_days<{{context_days}} AS truncated_window
 FROM staging.operation_intervals o JOIN context c USING(operation_id)
)
SELECT *,after_theo_per_hour-before_theo_per_hour AS theo_rate_change,
 CASE WHEN available_at_utc IS NULL THEN 'open_ticket'
      WHEN truncated_window THEN 'truncated_window'
      WHEN context_changed THEN 'changed_placement_or_configuration'
      WHEN overlapping_faults THEN 'overlapping_faults'
      WHEN before_available_hours=0 OR after_available_hours=0 THEN 'no_available_exposure'
      ELSE 'comparable' END AS comparison_status
FROM base ORDER BY operation_id;
