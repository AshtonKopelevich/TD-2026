CREATE TABLE staging.loyalty_events AS
SELECT l.*,staging.gaming_date(event_at_utc) AS gaming_date,i.opening_tier
FROM raw.loyalty_ledger l JOIN staging.player_identity i USING(player_id);

CREATE TABLE staging.ledger_player_day AS
SELECT player_id,gaming_date,
 count(*) FILTER(WHERE event_type='redeem')::BIGINT AS comps_redeemed,
 sum(CASE WHEN event_type='award' THEN points_delta ELSE 0 END)::BIGINT AS points_earned,
 -sum(CASE WHEN event_type='redeem' THEN points_delta ELSE 0 END)::BIGINT AS points_redeemed,
 sum(CASE WHEN event_type='redeem' THEN economic_cost_cents*0.01 ELSE 0 END)::DECIMAL(24,2) AS comp_cost_usd,
 sum(CASE WHEN event_type='redeem' THEN face_value_cents*0.01 ELSE 0 END)::DECIMAL(24,2) AS comp_face_value_usd
FROM staging.loyalty_events GROUP BY player_id,gaming_date;
