CREATE TABLE staging.comp_daily_totals AS
SELECT c.gaming_date,date_trunc('month',c.gaming_date)::DATE AS month_start,
 coalesce(sum(tracked_coin_in_usd),0)::DECIMAL(24,2) AS tracked_coin_in_usd,
 coalesce(sum(tracked_payout_usd),0)::DECIMAL(24,2) AS tracked_payout_usd,
 coalesce(sum(tracked_theo_usd),0)::DECIMAL(28,8) AS tracked_theo_usd,
 coalesce(sum(linked_pos_cash_usd),0)::DECIMAL(24,2) AS linked_pos_cash_usd,
 coalesce(sum(linked_pos_cogs_usd),0)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 coalesce(sum(comp_cost_usd),0)::DECIMAL(24,2) AS comp_cost_usd,
 coalesce(sum(comp_face_value_usd),0)::DECIMAL(24,2) AS comp_face_value_usd,
 coalesce(sum(points_earned),0)::BIGINT AS points_earned,coalesce(sum(points_redeemed),0)::BIGINT AS points_redeemed,
 coalesce(sum(points_balance_start),0)::BIGINT AS points_balance_start,
 coalesce(sum(points_balance_end),0)::BIGINT AS points_balance_end,
 coalesce(sum(active_players),0)::BIGINT AS active_players
FROM raw.calendar_day c CROSS JOIN staging.analysis_window w
LEFT JOIN staging.comp_cohort_day d USING(gaming_date)
WHERE c.gaming_date BETWEEN w.start_date AND w.end_date GROUP BY c.gaming_date;

CREATE TABLE marts.mart_comps_daily AS
SELECT m.*,NULL::BOOLEAN AS policy_change_candidate,s.change_method,s.change_status
FROM staging.comp_metrics('staging.comp_daily_totals') m CROSS JOIN staging.guest_settings s
ORDER BY gaming_date;
