-- Pseudo-outages hold out the target's entire gaming day from its healthy
-- reference. Other-bank peers exclude the target bank at the evaluation hour.
CREATE TABLE diagnostics.downtime_validation_cases AS
SELECT h.machine_id,h.hour_start_utc,h.hour_band,h.neighbor_count,
 (reference_n-day_n)::BIGINT AS reference_hours,h.theo_usd AS actual_theo_usd,
 (peer_theo_rate*(reference_theo-day_theo)/(reference_peer_theo-day_peer_theo))::DOUBLE AS predicted_theo_usd
FROM staging.hourly_reference h CROSS JOIN staging.downtime_settings s
WHERE h.healthy AND h.neighbor_count>=s.min_peers AND reference_n-day_n>=s.min_reference_hours
 AND reference_peer_theo-day_peer_theo>0
ORDER BY hash(h.machine_id,h.hour_start_utc,{{seed}}) LIMIT {{sample_size}};

CREATE TABLE diagnostics.downtime_model_validation AS
SELECT hour_band,count(*)::BIGINT AS cases,
 avg(abs(actual_theo_usd-predicted_theo_usd))::DOUBLE AS mae_usd_per_hour,
 quantile_cont(abs(actual_theo_usd-predicted_theo_usd),{{error_quantile}})::DOUBLE AS error_range_usd_per_hour
FROM diagnostics.downtime_validation_cases GROUP BY hour_band
UNION ALL SELECT NULL::BIGINT,count(*)::BIGINT,
 avg(abs(actual_theo_usd-predicted_theo_usd))::DOUBLE,
 quantile_cont(abs(actual_theo_usd-predicted_theo_usd),{{error_quantile}})::DOUBLE
FROM diagnostics.downtime_validation_cases;

CREATE TABLE staging.hourly_estimates AS
WITH fit AS (
 SELECT h.*,(scheduled_seconds-available_seconds)::BIGINT AS downtime_seconds,
 CASE WHEN reference_n>=s.min_reference_hours THEN reference_theo/nullif(reference_peer_theo,0) END AS usual_rate_ratio,
 CASE WHEN reference_n>=s.min_reference_hours THEN reference_coin/nullif(reference_peer_coin,0) END AS usual_coin_in_rate_ratio,
 CASE WHEN b.cases>=s.min_validation THEN b.error_range_usd_per_hour
      WHEN g.cases>=s.min_validation THEN g.error_range_usd_per_hour END AS error_per_hour,
 coalesce(h.available_seconds=h.scheduled_seconds AND h.scheduled_seconds=3600 AND h.paid_spins=0
   AND h.coin_in_usd=0 AND h.neighbor_count>=s.min_peers AND h.peer_occupancy>=s.busy_threshold,false) AS zero_busy,
 CASE WHEN downtime_seconds=0 THEN 'no_reported_downtime'
      WHEN neighbor_count<s.min_peers THEN 'insufficient_peers'
      WHEN reference_n<s.min_reference_hours THEN 'insufficient_reference'
      WHEN usual_rate_ratio IS NULL OR usual_coin_in_rate_ratio IS NULL THEN 'zero_reference_demand'
      ELSE 'estimated' END AS estimate_status
 FROM staging.hourly_reference h CROSS JOIN staging.downtime_settings s
 LEFT JOIN diagnostics.downtime_model_validation b USING(hour_band)
 CROSS JOIN (SELECT * FROM diagnostics.downtime_model_validation WHERE hour_band IS NULL) g
), lagged AS (
 SELECT *,lag(zero_busy) OVER w AS previous_zero,lag(hour_start_utc) OVER w AS previous_hour
 FROM fit WINDOW w AS (PARTITION BY machine_id,placement_id ORDER BY hour_start_utc)
), islands AS (
 SELECT *,sum(CASE WHEN zero_busy AND previous_zero AND previous_hour=hour_start_utc-INTERVAL '1 hour'
                  THEN 0 ELSE 1 END) OVER(PARTITION BY machine_id,placement_id ORDER BY hour_start_utc) AS run_id
 FROM lagged
)
SELECT *,count(*) FILTER(WHERE zero_busy) OVER(PARTITION BY machine_id,placement_id,run_id) AS zero_run_length,
 CASE WHEN downtime_seconds=0 THEN 0 WHEN estimate_status='estimated'
      THEN peer_coin_rate*usual_coin_in_rate_ratio*(downtime_seconds/3600.0) END::DECIMAL(24,2) AS estimated_lost_coin_in_usd,
 CASE WHEN downtime_seconds=0 THEN 0 WHEN estimate_status='estimated'
      THEN peer_theo_rate*usual_rate_ratio*(downtime_seconds/3600.0) END::DECIMAL(28,8) AS estimated_lost_theo_usd
FROM islands;

CREATE TABLE marts.mart_downtime_hourly AS
WITH attribution AS (
 SELECT h.*,coalesce(o.ticket_seconds,0)::BIGINT AS ticket_overlap_seconds,
 least(h.downtime_seconds,coalesce(o.fault_seconds,0))::BIGINT AS fault_downtime_seconds,
 least(h.downtime_seconds-fault_downtime_seconds,coalesce(o.planned_seconds,0))::BIGINT AS planned_downtime_seconds,
 (h.downtime_seconds-fault_downtime_seconds-planned_downtime_seconds)::BIGINT AS other_downtime_seconds
 FROM staging.hourly_estimates h LEFT JOIN staging.outage_allocations o USING(machine_id,hour_start_utc)
)
SELECT h.machine_id,h.location_id,h.zone_id,h.bank_id,h.config_id,h.manufacturer,h.hour_start_utc,
 h.gaming_date,h.local_hour,h.hour_band,h.utc_offset,h.scheduled_seconds,h.available_seconds,h.occupied_seconds,
 h.downtime_seconds,h.coin_in_usd,h.payout_usd,h.theo_usd,
 h.fault_downtime_seconds,h.planned_downtime_seconds,h.other_downtime_seconds,h.ticket_overlap_seconds,
 greatest(h.downtime_seconds-h.ticket_overlap_seconds,0)::BIGINT AS unexplained_downtime_seconds,
 h.neighbor_count,nullif(h.neighbor_available_hours,0)::DOUBLE AS neighbor_available_hours,
 h.reference_n::BIGINT AS reference_hours,h.usual_rate_ratio,h.usual_coin_in_rate_ratio,
 h.estimated_lost_coin_in_usd,h.estimated_lost_theo_usd,
 CASE WHEN h.downtime_seconds=0 THEN 0 WHEN h.estimate_status='estimated' AND h.error_per_hour IS NOT NULL
      THEN greatest(0,h.estimated_lost_theo_usd-h.error_per_hour*(h.downtime_seconds/3600.0)) END::DECIMAL(28,8) AS lost_theo_low_usd,
 CASE WHEN h.downtime_seconds=0 THEN 0 WHEN h.estimate_status='estimated' AND h.error_per_hour IS NOT NULL
      THEN h.estimated_lost_theo_usd+h.error_per_hour*(h.downtime_seconds/3600.0) END::DECIMAL(28,8) AS lost_theo_high_usd,
 CASE WHEN s.busy_threshold IS NULL THEN NULL
      WHEN h.neighbor_count<s.min_peers OR h.available_seconds<>h.scheduled_seconds OR h.scheduled_seconds<>3600 THEN NULL
      ELSE h.zero_busy AND h.zero_run_length>=s.zero_run_hours END AS hidden_downtime_flag,
 CASE WHEN s.busy_threshold IS NULL THEN 'not_configured'
      WHEN h.neighbor_count<s.min_peers THEN 'insufficient_peers'
      WHEN h.available_seconds<>h.scheduled_seconds OR h.scheduled_seconds<>3600 THEN 'not_fully_available'
      ELSE 'evaluated' END AS hidden_downtime_status,
 'other_bank_matched_healthy_reference'::VARCHAR AS estimate_method,h.estimate_status,
 CASE WHEN h.downtime_seconds=0 THEN 'no_reported_downtime'
      WHEN h.estimate_status<>'estimated' THEN 'estimate_unavailable'
      WHEN h.error_per_hour IS NULL THEN 'insufficient_validation'
      ELSE 'empirical_error_scenario' END AS uncertainty_status,
 CASE WHEN h.ticket_overlap_seconds=h.downtime_seconds THEN 'matched'
      WHEN h.ticket_overlap_seconds>h.downtime_seconds THEN 'ticket_exceeds_meter' ELSE 'unexplained_meter_downtime' END AS outage_attribution_status,
 staff.staff_hours AS available_tech_staff_hours
FROM attribution h CROSS JOIN staging.downtime_settings s
LEFT JOIN staging.hourly_staff staff USING(zone_id,hour_start_utc)
ORDER BY h.machine_id,h.hour_start_utc;

CREATE TABLE diagnostics.downtime_coverage AS
SELECT count(*)::BIGINT AS installed_hour_rows,
 count(*) FILTER(WHERE downtime_seconds>0)::BIGINT AS outage_hour_rows,
 count(*) FILTER(WHERE estimate_status='estimated')::BIGINT AS estimated_hour_rows,
 sum(downtime_seconds)::BIGINT AS reported_downtime_seconds,
 coalesce(sum(downtime_seconds) FILTER(WHERE estimate_status='estimated'),0)::BIGINT AS estimated_downtime_seconds,
 sum(unexplained_downtime_seconds)::BIGINT AS unexplained_seconds,
 count(*) FILTER(WHERE outage_attribution_status='ticket_exceeds_meter')::BIGINT AS ticket_excess_hours,
 coalesce(sum(estimated_lost_theo_usd),0)::DECIMAL(28,8) AS estimated_gross_lost_theo_usd,
 'Gross estimates only; player substitution and net floor loss are not identified.'::VARCHAR AS limitation
FROM marts.mart_downtime_hourly;
