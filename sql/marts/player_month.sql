CREATE TABLE marts.mart_player_month AS
SELECT p.player_id,cast(p.period_month||'-01' AS DATE) AS month_start,
 i.home_region,i.age_band,i.opening_tier,coalesce(nullif(trim(p.tier_end),''),'Unknown') AS tier_end,
 p.observed_visits,p.incomplete_visits,p.sessions,p.carded_play_hours,
 p.tracked_coin_in_usd::DECIMAL(24,2) AS tracked_coin_in_usd,
 p.tracked_payout_usd::DECIMAL(24,2) AS tracked_payout_usd,
 p.tracked_net_usd::DECIMAL(24,2) AS tracked_net_usd,
 (-p.tracked_net_usd)::DECIMAL(24,2) AS actual_tracked_loss_usd,
 p.theo_usd::DECIMAL(28,8) AS theo_usd,p.luck_residual_usd::DECIMAL(28,8) AS luck_residual_usd,
 p.linked_pos_cash_usd::DECIMAL(24,2) AS linked_pos_cash_usd,
 p.linked_pos_cogs_usd::DECIMAL(24,2) AS linked_pos_cogs_usd,
 p.comp_face_value_usd::DECIMAL(24,2) AS comp_face_value_usd,
 p.comp_cost_usd::DECIMAL(24,2) AS comp_cost_usd,
 p.tracked_contribution_usd::DECIMAL(24,2) AS tracked_contribution_usd,
 p.comps_redeemed,p.points_earned,p.points_redeemed,(p.tracked_net_usd>0) AS winner_flag,
 NULL::BOOLEAN AS above_expected_loss_flag,settings.protective_status
FROM raw.player_period p JOIN staging.player_identity i USING(player_id)
CROSS JOIN staging.analysis_window w CROSS JOIN staging.guest_settings settings
WHERE cast(p.period_month||'-01' AS DATE) BETWEEN w.start_date AND w.end_date
ORDER BY p.player_id,month_start;
