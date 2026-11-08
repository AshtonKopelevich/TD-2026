CREATE TABLE staging.comp_tier_month_totals AS
WITH active AS (
 SELECT opening_tier,date_trunc('month',gaming_date)::DATE AS month_start,
 count(DISTINCT player_id)::BIGINT AS active_players FROM staging.player_day GROUP BY opening_tier,month_start
), enrolled AS (
 SELECT d.opening_tier,d.month_start,count(i.player_id)::BIGINT AS cohort_players
 FROM (SELECT DISTINCT opening_tier,month_start FROM staging.comp_cohort_day) d
 LEFT JOIN staging.player_identity i ON i.opening_tier=d.opening_tier AND i.enrolled_gaming_date<=last_day(d.month_start)
 GROUP BY d.opening_tier,d.month_start
)
SELECT d.opening_tier,d.month_start,e.cohort_players,coalesce(a.active_players,0)::BIGINT AS active_players,
 sum(tracked_coin_in_usd)::DECIMAL(24,2) AS tracked_coin_in_usd,
 sum(tracked_payout_usd)::DECIMAL(24,2) AS tracked_payout_usd,
 sum(tracked_theo_usd)::DECIMAL(28,8) AS tracked_theo_usd,
 sum(linked_pos_cash_usd)::DECIMAL(24,2) AS linked_pos_cash_usd,
 sum(linked_pos_cogs_usd)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 sum(comp_cost_usd)::DECIMAL(24,2) AS comp_cost_usd,
 sum(comp_face_value_usd)::DECIMAL(24,2) AS comp_face_value_usd,
 sum(points_earned)::BIGINT AS points_earned,sum(points_redeemed)::BIGINT AS points_redeemed,
 arg_min(points_balance_start,gaming_date)::BIGINT AS points_balance_start,
 arg_max(points_balance_end,gaming_date)::BIGINT AS points_balance_end
FROM staging.comp_cohort_day d LEFT JOIN active a USING(opening_tier,month_start)
JOIN enrolled e USING(opening_tier,month_start)
GROUP BY d.opening_tier,d.month_start,e.cohort_players,a.active_players;

CREATE TABLE marts.mart_comps_tier_month AS
SELECT m.*,NULL::BOOLEAN AS policy_change_candidate,s.change_status AS comparison_status
FROM staging.comp_metrics('staging.comp_tier_month_totals') m CROSS JOIN staging.guest_settings s
ORDER BY opening_tier,month_start;
