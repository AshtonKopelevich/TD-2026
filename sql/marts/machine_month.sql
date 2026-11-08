CREATE TABLE marts.mart_machine_month AS
WITH totals AS (
 SELECT machine_id, month_start, min(gaming_date) AS period_start, max(gaming_date) AS period_end,
 count(*)::BIGINT AS active_days, any_value(manufacturer) AS manufacturer, any_value(lease_class) AS lease_class,
 sum(scheduled_seconds)::BIGINT AS scheduled_seconds, sum(available_seconds)::BIGINT AS available_seconds,
 sum(occupied_seconds)::BIGINT AS occupied_seconds, sum(paid_spins)::BIGINT AS paid_spins, sum(carded_spins)::BIGINT AS carded_spins,
 sum(coin_in_usd)::DECIMAL(24,2) AS coin_in_usd, sum(payout_usd)::DECIMAL(24,2) AS payout_usd,
 sum(house_win_usd)::DECIMAL(24,2) AS house_win_usd,
 sum(carded_coin_in_usd)::DECIMAL(24,2) AS carded_coin_in_usd, sum(carded_payout_usd)::DECIMAL(24,2) AS carded_payout_usd,
 sum(theo_usd)::DECIMAL(28,8) AS theo_usd, sum(carded_theo_usd)::DECIMAL(28,8) AS carded_theo_usd,
 sum(luck_residual_usd)::DECIMAL(28,8) AS luck_residual_usd,
 sum(lease_cost_usd)::DECIMAL(24,2) AS lease_cost_usd, sum(service_cost_usd)::DECIMAL(24,2) AS service_cost_usd,
 sum(power_cost_usd)::DECIMAL(24,2) AS power_cost_usd, sum(repair_cost_usd)::DECIMAL(24,2) AS repair_cost_usd,
 sum(machine_cost_usd)::DECIMAL(24,2) AS machine_cost_usd, sum(actual_contribution_usd)::DECIMAL(24,2) AS actual_contribution_usd,
 sum(expected_contribution_usd)::DECIMAL(28,8) AS expected_contribution_usd,
 count(DISTINCT location_id)::BIGINT AS location_count, count(DISTINCT config_id)::BIGINT AS config_count,
 sum(outcome_variance_usd2)::DOUBLE AS outcome_variance_usd2
 FROM marts.mart_machine_daily GROUP BY machine_id,month_start
)
SELECT *, available_seconds::DOUBLE/nullif(scheduled_seconds,0) AS availability_ratio,
 occupied_seconds::DOUBLE/nullif(available_seconds,0) AS occupancy_ratio,
 house_win_usd::DOUBLE/nullif(coin_in_usd,0) AS observed_hold,
 theo_usd::DOUBLE/nullif(coin_in_usd,0) AS expected_hold,
 carded_coin_in_usd::DOUBLE/nullif(coin_in_usd,0) AS carded_coin_in_share,
 coin_in_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS coin_in_per_available_hour,
 theo_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS theo_per_available_hour,
 expected_contribution_usd::DOUBLE/nullif(available_seconds/3600.0,0) AS expected_contribution_per_available_hour,
 NULL::DOUBLE AS luck_z_score, NULL::DOUBLE AS luck_p_value, NULL::DOUBLE AS luck_q_value,
 NULL::DOUBLE AS bootstrap_hold_gap_low, NULL::DOUBLE AS bootstrap_hold_gap_high,
 'not_implemented'::VARCHAR AS statistical_status
FROM totals ORDER BY machine_id,month_start;
