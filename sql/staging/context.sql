-- Aggregate context independently before any fact joins.
CREATE TABLE staging.events_daily AS
SELECT c.gaming_date, string_agg(e.name, ' | ' ORDER BY e.event_id) AS events_active
FROM raw.calendar_day c LEFT JOIN raw.events e
 ON c.gaming_date BETWEEN e.start_date AND e.end_date
GROUP BY c.gaming_date;

CREATE TABLE staging.weather_daily AS
SELECT source_date, CASE WHEN nullif(trim(tmax_qflag),'') IS NULL THEN tmax_c::DOUBLE END AS tmax_c,
 CASE WHEN nullif(trim(prcp_qflag),'') IS NULL THEN prcp_mm::DOUBLE END AS prcp_mm,
 CASE WHEN prcp_mm IS NOT NULL AND nullif(trim(prcp_qflag),'') IS NULL THEN coalesce(prcp_mflag='T',false) END AS trace,
 CASE WHEN nullif(trim(tmax_qflag),'') IS NOT NULL OR nullif(trim(prcp_qflag),'') IS NOT NULL THEN 'quality_flagged'
      WHEN tmax_c IS NULL OR prcp_mm IS NULL THEN 'partial' ELSE 'complete' END AS weather_status
FROM raw.weather_daily WHERE station_id='USW00023169';

-- No sensor installation/schedule table is supplied. Explicitly infer a stable
-- full-day roster from each sensor's zone across the source release. Missing
-- feed rows therefore lower coverage rather than disappearing from its denominator.
CREATE TABLE staging.sensor_roster AS
SELECT DISTINCT sensor_id, zone_id FROM raw.zone_traffic_hourly;

CREATE TABLE staging.traffic_daily AS
SELECT t.zone_id, c.gaming_date,
 sum(CASE WHEN t.coverage_minutes>0 AND t.counter_status IN ('ok','partial') THEN t.entries_count END)::BIGINT AS entries_observed,
 sum(t.coverage_minutes::BIGINT*60)::BIGINT AS observed_seconds,
 count(*)::BIGINT AS reported_hours
FROM raw.zone_traffic_hourly t JOIN raw.calendar_day c
 ON t.hour_start_utc >= c.gaming_day_start_utc AND t.hour_start_utc < c.gaming_day_end_utc
GROUP BY t.zone_id,c.gaming_date;
