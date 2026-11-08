CREATE TABLE marts.mart_visits_month AS
SELECT month_start,home_region,age_band,opening_tier,count(*)::BIGINT AS observed_visits,
 count(*) FILTER(WHERE observation_complete)::BIGINT AS complete_visits,
 count(*) FILTER(WHERE NOT observation_complete)::BIGINT AS incomplete_visits,
 count(*) FILTER(WHERE has_gaming)::BIGINT AS visits_with_gaming,
 count(*) FILTER(WHERE has_gaming AND observation_complete)::BIGINT AS complete_gaming_visits,
 count(*) FILTER(WHERE has_gaming AND observation_complete AND payout_usd>coin_in_usd)::BIGINT AS winning_visits,
 count(DISTINCT player_id)::BIGINT AS unique_players,
 sum(coin_in_usd)::DECIMAL(24,2) AS visit_assigned_coin_in_usd,
 sum(payout_usd)::DECIMAL(24,2) AS visit_assigned_payout_usd,
 sum(payout_usd-coin_in_usd)::DECIMAL(24,2) AS visit_assigned_player_net_usd,
 sum(pos_cash_usd)::DECIMAL(24,2) AS visit_assigned_pos_cash_usd,
 sum(theo_usd)::DECIMAL(28,8) AS visit_assigned_theo_usd,
 sum(coin_in_usd)::DOUBLE/count(*) AS coin_in_per_visit,
 count(*) FILTER(WHERE has_gaming AND observation_complete AND payout_usd>coin_in_usd)::DOUBLE/
 nullif(count(*) FILTER(WHERE has_gaming AND observation_complete),0) AS winner_share_complete_visits
FROM staging.visit_facts CROSS JOIN staging.analysis_window w
WHERE first_gaming_date BETWEEN w.start_date AND w.end_date
GROUP BY month_start,home_region,age_band,opening_tier
ORDER BY month_start,home_region,age_band,opening_tier;
