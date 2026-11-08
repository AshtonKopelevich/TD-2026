CREATE TABLE marts.mart_zone_daily AS
WITH zones AS (
 SELECT DISTINCT zone_id FROM raw.floor_locations WHERE node_type='slot'
), machines AS (
 SELECT zone_id,gaming_date,count(*)::BIGINT AS active_machines,
 sum(scheduled_seconds)::BIGINT AS scheduled_seconds,sum(available_seconds)::BIGINT AS available_seconds,
 sum(occupied_seconds)::BIGINT AS occupied_seconds,sum(coin_in_usd)::DECIMAL(24,2) AS coin_in_usd,
 sum(house_win_usd)::DECIMAL(24,2) AS house_win_usd,sum(theo_usd)::DECIMAL(28,8) AS theo_usd
 FROM marts.mart_machine_daily GROUP BY zone_id,gaming_date
), roster AS (
 SELECT zone_id,count(*)::BIGINT AS sensor_count FROM staging.sensor_roster GROUP BY zone_id
), base AS (
 SELECT z.zone_id,l.name AS zone_name,c.gaming_date,date_trunc('month',c.gaming_date)::DATE AS month_start,
 coalesce(m.active_machines,0)::BIGINT AS active_machines,
 coalesce(m.scheduled_seconds,0)::BIGINT AS scheduled_seconds,
 coalesce(m.available_seconds,0)::BIGINT AS available_seconds,
 coalesce(m.occupied_seconds,0)::BIGINT AS occupied_seconds,
 coalesce(m.coin_in_usd,0)::DECIMAL(24,2) AS coin_in_usd,
 coalesce(m.house_win_usd,0)::DECIMAL(24,2) AS house_win_usd,
 coalesce(m.theo_usd,0)::DECIMAL(28,8) AS theo_usd,t.entries_observed,
 coalesce(t.observed_seconds,0)::BIGINT AS counter_observed_seconds,
 (coalesce(r.sensor_count,0)*c.scheduled_seconds)::BIGINT AS counter_expected_seconds,
 (coalesce(r.sensor_count,0)*c.scheduled_seconds-coalesce(t.reported_hours,0)*3600)::BIGINT AS counter_missing_seconds,
 coalesce(r.sensor_count,0)::BIGINT AS sensor_count,
 'inferred_full_day_release_roster'::VARCHAR AS counter_schedule_basis
 FROM zones z CROSS JOIN raw.calendar_day c CROSS JOIN staging.analysis_window limits
 LEFT JOIN raw.floor_locations l ON l.location_id=z.zone_id AND l.node_type='zone'
 LEFT JOIN machines m ON m.zone_id=z.zone_id AND m.gaming_date=c.gaming_date
 LEFT JOIN roster r ON r.zone_id=z.zone_id
 LEFT JOIN staging.traffic_daily t ON t.zone_id=z.zone_id AND t.gaming_date=c.gaming_date
 WHERE c.gaming_date BETWEEN limits.start_date AND limits.end_date
)
SELECT *, coin_in_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS coin_in_per_available_hour,
 theo_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS theo_per_available_hour,
 counter_observed_seconds::DOUBLE/nullif(counter_expected_seconds,0) AS counter_coverage_ratio,
 CASE WHEN sensor_count=0 THEN 'no_sensor'
      WHEN counter_observed_seconds=counter_expected_seconds THEN 'complete'
      WHEN counter_observed_seconds>0 THEN 'partial'
      WHEN counter_missing_seconds=counter_expected_seconds THEN 'missing'
      ELSE 'offline' END AS traffic_status
FROM base ORDER BY zone_id,gaming_date;
