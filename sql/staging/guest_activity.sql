-- Every fact is already at player x day before joining. No session/POS fanout.
CREATE TABLE staging.player_day AS
WITH keys AS (
 SELECT player_id,gaming_date FROM staging.session_player_day
 UNION SELECT player_id,gaming_date FROM staging.receipt_player_day
 UNION SELECT player_id,gaming_date FROM staging.ledger_player_day
)
SELECT k.player_id,k.gaming_date,i.opening_tier,
 coalesce(s.tracked_coin_in_usd,0)::DECIMAL(24,2) AS tracked_coin_in_usd,
 coalesce(s.tracked_payout_usd,0)::DECIMAL(24,2) AS tracked_payout_usd,
 coalesce(s.tracked_theo_usd,0)::DECIMAL(30,10) AS tracked_theo_usd,
 coalesce(f.linked_pos_cash_usd,0)::DECIMAL(24,2) AS linked_pos_cash_usd,
 coalesce(f.linked_pos_cogs_usd,0)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 coalesce(l.comp_cost_usd,0)::DECIMAL(24,2) AS comp_cost_usd,
 coalesce(l.comp_face_value_usd,0)::DECIMAL(24,2) AS comp_face_value_usd,
 coalesce(l.points_earned,0)::BIGINT AS points_earned,coalesce(l.points_redeemed,0)::BIGINT AS points_redeemed
 ,coalesce(l.comps_redeemed,0)::BIGINT AS comps_redeemed
FROM keys k JOIN staging.player_identity i USING(player_id)
CROSS JOIN staging.analysis_window w
LEFT JOIN staging.session_player_day s USING(player_id,gaming_date)
LEFT JOIN staging.receipt_player_day f USING(player_id,gaming_date)
LEFT JOIN staging.ledger_player_day l USING(player_id,gaming_date)
WHERE k.gaming_date BETWEEN w.start_date AND w.end_date;

CREATE TABLE staging.player_fact_month AS
SELECT player_id,date_trunc('month',gaming_date)::DATE AS month_start,
 sum(tracked_coin_in_usd)::DECIMAL(24,2) AS tracked_coin_in_usd,
 sum(tracked_payout_usd)::DECIMAL(24,2) AS tracked_payout_usd,
 sum(tracked_theo_usd)::DECIMAL(30,10) AS tracked_theo_usd,
 sum(linked_pos_cash_usd)::DECIMAL(24,2) AS linked_pos_cash_usd,
 sum(linked_pos_cogs_usd)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 sum(comp_cost_usd)::DECIMAL(24,2) AS comp_cost_usd,
 sum(comp_face_value_usd)::DECIMAL(24,2) AS comp_face_value_usd,
 sum(points_earned)::BIGINT AS points_earned,sum(points_redeemed)::BIGINT AS points_redeemed,
 sum(comps_redeemed)::BIGINT AS comps_redeemed
FROM staging.player_day GROUP BY player_id,month_start;

CREATE TABLE staging.comp_cohort_day AS
WITH tiers AS (SELECT DISTINCT opening_tier FROM staging.player_identity),
opening AS (
 SELECT l.opening_tier,sum(points_delta)::BIGINT AS balance
 FROM staging.loyalty_events l CROSS JOIN staging.analysis_window w
 WHERE l.gaming_date>=date_trunc('year',w.start_date)::DATE AND l.gaming_date<w.start_date
 GROUP BY l.opening_tier
), totals AS (
 SELECT opening_tier,gaming_date,
 sum(tracked_coin_in_usd)::DECIMAL(24,2) AS tracked_coin_in_usd,
 sum(tracked_payout_usd)::DECIMAL(24,2) AS tracked_payout_usd,
 sum(tracked_theo_usd)::DECIMAL(30,10) AS tracked_theo_usd,
 sum(linked_pos_cash_usd)::DECIMAL(24,2) AS linked_pos_cash_usd,
 sum(linked_pos_cogs_usd)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 sum(comp_cost_usd)::DECIMAL(24,2) AS comp_cost_usd,sum(comp_face_value_usd)::DECIMAL(24,2) AS comp_face_value_usd,
 sum(points_earned)::BIGINT AS points_earned,sum(points_redeemed)::BIGINT AS points_redeemed,
 count(*)::BIGINT AS active_players
 FROM staging.player_day GROUP BY opening_tier,gaming_date
), grid AS (
 SELECT t.opening_tier,c.gaming_date,date_trunc('month',c.gaming_date)::DATE AS month_start,
 coalesce(a.tracked_coin_in_usd,0)::DECIMAL(24,2) AS tracked_coin_in_usd,
 coalesce(a.tracked_payout_usd,0)::DECIMAL(24,2) AS tracked_payout_usd,
 coalesce(a.tracked_theo_usd,0)::DECIMAL(30,10) AS tracked_theo_usd,
 coalesce(a.linked_pos_cash_usd,0)::DECIMAL(24,2) AS linked_pos_cash_usd,
 coalesce(a.linked_pos_cogs_usd,0)::DECIMAL(24,2) AS linked_pos_cogs_usd,
 coalesce(a.comp_cost_usd,0)::DECIMAL(24,2) AS comp_cost_usd,
 coalesce(a.comp_face_value_usd,0)::DECIMAL(24,2) AS comp_face_value_usd,
 coalesce(a.points_earned,0)::BIGINT AS points_earned,coalesce(a.points_redeemed,0)::BIGINT AS points_redeemed,
 coalesce(a.active_players,0)::BIGINT AS active_players,coalesce(o.balance,0)::BIGINT AS initial_balance
 FROM tiers t CROSS JOIN raw.calendar_day c CROSS JOIN staging.analysis_window w
 LEFT JOIN totals a ON a.opening_tier=t.opening_tier AND a.gaming_date=c.gaming_date
 LEFT JOIN opening o ON o.opening_tier=t.opening_tier
 WHERE c.gaming_date BETWEEN w.start_date AND w.end_date
)
SELECT *, (initial_balance+sum(points_earned-points_redeemed) OVER (
 PARTITION BY opening_tier ORDER BY gaming_date ROWS UNBOUNDED PRECEDING))::BIGINT AS points_balance_end,
 (initial_balance+sum(points_earned-points_redeemed) OVER (
 PARTITION BY opening_tier ORDER BY gaming_date ROWS UNBOUNDED PRECEDING)-points_earned+points_redeemed)::BIGINT AS points_balance_start
FROM grid;

-- Shared derived metrics for daily and monthly aggregates (ratios of sums).
CREATE MACRO staging.comp_metrics(t) AS TABLE
WITH amounts AS (
 SELECT *, (tracked_coin_in_usd-tracked_payout_usd)::DECIMAL(24,2) AS actual_tracked_loss_usd,
 (tracked_coin_in_usd-tracked_payout_usd+linked_pos_cash_usd)::DECIMAL(24,2) AS total_tracked_spend_usd,
 (tracked_coin_in_usd-tracked_payout_usd+linked_pos_cash_usd-linked_pos_cogs_usd)::DECIMAL(24,2) AS tracked_contribution_usd,
 (points_earned-points_redeemed)::BIGINT AS points_balance_change
 FROM query_table(t)
)
SELECT *,CASE WHEN actual_tracked_loss_usd>0 THEN comp_cost_usd::DOUBLE/actual_tracked_loss_usd END AS comp_cost_per_actual_loss,
 CASE WHEN total_tracked_spend_usd>0 THEN comp_cost_usd::DOUBLE/total_tracked_spend_usd END AS comp_cost_per_total_spend,
 comp_cost_usd::DOUBLE/nullif(tracked_coin_in_usd,0) AS comp_cost_per_coin_in,
 tracked_theo_usd::DOUBLE/nullif(comp_cost_usd,0) AS theo_per_comp_cost,
 CASE WHEN actual_tracked_loss_usd>0 THEN 'positive_denominator' WHEN actual_tracked_loss_usd=0 THEN 'zero_denominator' ELSE 'negative_denominator' END AS actual_loss_ratio_status,
 CASE WHEN total_tracked_spend_usd>0 THEN 'positive_denominator' WHEN total_tracked_spend_usd=0 THEN 'zero_denominator' ELSE 'negative_denominator' END AS total_spend_ratio_status
FROM amounts;
