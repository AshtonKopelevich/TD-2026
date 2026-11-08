CREATE TABLE marts.mart_machine_scorecard AS
WITH totals AS (
 SELECT d.machine_id,count(*)::BIGINT AS active_days,
 count(*) FILTER(WHERE d.available_seconds>0)::BIGINT AS exposure_days,
 sum(d.outcome_variance_usd2)::DOUBLE AS outcome_variance_usd2,
 {{sum_measures}}
 FROM marts.mart_machine_daily d GROUP BY d.machine_id
), covered AS (
 SELECT * FROM staging.machine_peer_day WHERE peer_count>={{min_peers}} AND target_hours>0
), peers AS (
 SELECT machine_id,count(*)::BIGINT AS peer_coverage_days,
 sum(peer_theo_rate*target_hours)/nullif(sum(target_hours),0) AS peer_theo_per_hour,
 sum(theo_usd)::DOUBLE/nullif(sum(peer_theo_rate*target_hours),0) AS peer_rate_ratio,
 sum(peer_coin_rate*target_hours)/nullif(sum(target_hours),0) AS peer_coin_in_per_hour,
 sum(coin_in_usd)::DOUBLE/nullif(sum(peer_coin_rate*target_hours),0) AS peer_coin_in_rate_ratio,
 sum(peer_contribution_rate*target_hours)/nullif(sum(target_hours),0) AS peer_expected_contribution_per_hour,
 sum(floor_coin_rate*target_hours)/nullif(sum(target_hours),0) AS floor_coin_in_per_hour
 FROM covered GROUP BY machine_id
), faults AS (
 SELECT machine_id,count(*)::BIGINT AS eligible_fault_tickets,
 count(*) FILTER(WHERE after_theo_per_hour/before_theo_per_hour-1>={{rebound_gap}})::BIGINT AS rebound_fault_tickets
 FROM marts.mart_tickets WHERE event_type='fault_repair' AND comparison_status='comparable'
   AND before_theo_per_hour>0 AND after_theo_per_hour IS NOT NULL GROUP BY machine_id
), base AS (
 SELECT t.* EXCLUDE(exposure_days),w.start_date AS analysis_start,w.end_date AS analysis_end,
 available_seconds::DOUBLE/nullif(scheduled_seconds,0) AS availability_ratio,
 occupied_seconds::DOUBLE/nullif(available_seconds,0) AS occupancy_ratio,
 house_win_usd::DOUBLE/nullif(coin_in_usd,0) AS observed_hold,
 theo_usd::DOUBLE/nullif(coin_in_usd,0) AS expected_hold,
 carded_coin_in_usd::DOUBLE/nullif(coin_in_usd,0) AS carded_coin_in_share,
 coin_in_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS coin_in_per_available_hour,
 theo_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS theo_per_available_hour,
 expected_contribution_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS expected_contribution_per_available_hour,
 row_number() OVER(ORDER BY house_win_usd,t.machine_id)::BIGINT AS naive_rank,
 row_number() OVER(ORDER BY expected_contribution_per_available_hour ASC NULLS LAST,t.machine_id)::BIGINT AS adjusted_rank,
 coalesce(p.peer_coverage_days,0)::BIGINT AS peer_coverage_days,
 coalesce(p.peer_coverage_days,0)::DOUBLE/nullif(t.exposure_days,0) AS peer_coverage_fraction,
 p.* EXCLUDE(machine_id,peer_coverage_days),
 p.peer_coin_in_per_hour/nullif(p.floor_coin_in_per_hour,0) AS zone_to_floor_coin_ratio,
 s.* EXCLUDE(machine_id,period,active_days,outcome_variance_usd2),d.dependence_warning,
 coalesce(d.max_day_variance_share>{{variance_warning}},false)
   OR coalesce(d.max_day_wager_share>{{wager_warning}},false) AS exposure_concentration_warning,
 coalesce(f.eligible_fault_tickets,0)::BIGINT AS eligible_fault_tickets,
 coalesce(f.rebound_fault_tickets,0)::BIGINT AS rebound_fault_tickets
 FROM totals t CROSS JOIN staging.analysis_window w JOIN diagnostics.machine_statistics s
 ON s.machine_id=t.machine_id AND s.period='full'
 JOIN diagnostics.machine_dependence d ON d.machine_id=t.machine_id AND d.period='full'
 LEFT JOIN peers p ON p.machine_id=t.machine_id LEFT JOIN faults f ON f.machine_id=t.machine_id
), flags AS (
 SELECT *,naive_rank<=10 AS naive_bottom_10,
 CASE WHEN active_days>={{min_active}} AND positive_wager_days>={{min_positive}}
   AND {{min_coverage_days}} IS NOT NULL AND peer_coverage_days>={{min_coverage_days}}
   AND peer_coverage_fraction>={{min_coverage_fraction}}
 THEN peer_coin_in_rate_ratio<1-{{weak_gap}} AND peer_rate_ratio<1-{{weak_gap}} END AS weak_demand_flag,
 CASE WHEN active_days>={{min_active}} AND positive_wager_days>={{min_positive}}
   AND {{min_coverage_days}} IS NOT NULL AND peer_coverage_days>={{min_coverage_days}}
   AND peer_coverage_fraction>={{min_coverage_fraction}}
 THEN zone_to_floor_coin_ratio<1-{{weak_gap}} AND peer_coin_in_rate_ratio>=1-{{weak_gap}}
   AND zone_to_floor_coin_ratio*peer_coin_in_rate_ratio<1-{{weak_gap}} END AS location_flag,
 CASE WHEN active_days>={{min_active}} AND scheduled_seconds>0
 THEN 1-available_seconds::DOUBLE/scheduled_seconds>={{downtime_share}} END AS downtime_flag,
 CASE WHEN active_days>={{min_active}} AND eligible_fault_tickets>={{min_fault_tickets}}
 THEN rebound_fault_tickets::DOUBLE/eligible_fault_tickets>={{rebound_share}} END AS repair_rebound_flag,
 CASE WHEN active_days<{{min_active}} THEN 'insufficient_exposure'
   WHEN eligible_fault_tickets<{{min_fault_tickets}} THEN 'insufficient_comparable_tickets' ELSE 'available' END AS repair_evidence_status,
 CASE WHEN clt_eligible AND NOT coalesce(dependence_warning,false) AND NOT exposure_concentration_warning
 THEN luck_q_value<={{alpha}} END AS hold_anomaly_flag,
 CASE WHEN clt_eligible AND NOT coalesce(dependence_warning,false) AND NOT exposure_concentration_warning
 THEN luck_q_value>{{alpha}} AND (bootstrap_status<>'available'
   OR bootstrap_hold_gap_low<=0 AND bootstrap_hold_gap_high>=0) END AS luck_compatible,
 CASE WHEN clt_eligible AND bootstrap_status='available' THEN
   (luck_q_value<={{alpha}}) IS DISTINCT FROM (bootstrap_hold_gap_low>0 OR bootstrap_hold_gap_high<0)
   ELSE false END AS method_disagreement
 FROM base
)
SELECT *,''::VARCHAR AS primary_classification,''::VARCHAR AS classification_reason
FROM flags ORDER BY machine_id;
