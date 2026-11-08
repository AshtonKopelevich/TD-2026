CREATE TABLE staging.player_identity AS
SELECT player_id,coalesce(nullif(trim(home_region),''),'Unknown') AS home_region,
 coalesce(nullif(trim(age_band),''),'Unknown') AS age_band,
 coalesce(nullif(trim(opening_tier),''),'Unknown') AS opening_tier,
 staging.gaming_date(enrolled_at_utc) AS enrolled_gaming_date
FROM raw.players;

CREATE TABLE staging.session_player_day AS
SELECT player_id,gaming_date,sum(coin_in_cents*0.01)::DECIMAL(24,2) AS tracked_coin_in_usd,
 sum(payout_cents*0.01)::DECIMAL(24,2) AS tracked_payout_usd,
 (sum(theo_cents)*0.01)::DECIMAL(30,10) AS tracked_theo_usd
FROM raw.sessions GROUP BY player_id,gaming_date;

CREATE TABLE staging.visit_facts AS
WITH play AS (
 SELECT observed_visit_id,sum(coin_in_cents*0.01)::DECIMAL(24,2) AS coin_in_usd,
 sum(payout_cents*0.01)::DECIMAL(24,2) AS payout_usd,
 (sum(theo_cents)*0.01)::DECIMAL(30,10) AS theo_usd,count(*)::BIGINT AS segments
 FROM raw.sessions GROUP BY observed_visit_id
), pos AS (
 SELECT observed_visit_id,sum(cash_receipt_cents*0.01)::DECIMAL(24,2) AS cash_usd
 FROM raw.fnb_transactions WHERE observed_visit_id IS NOT NULL GROUP BY observed_visit_id
)
SELECT t.observed_visit_id,t.player_id,staging.gaming_date(t.first_observed_at_utc) AS first_gaming_date,
 date_trunc('month',staging.gaming_date(t.first_observed_at_utc))::DATE AS month_start,
 i.home_region,i.age_band,i.opening_tier,t.observation_complete,
 coalesce(p.segments,0)>0 AS has_gaming,coalesce(p.coin_in_usd,0)::DECIMAL(24,2) AS coin_in_usd,
 coalesce(p.payout_usd,0)::DECIMAL(24,2) AS payout_usd,
 coalesce(p.theo_usd,0)::DECIMAL(30,10) AS theo_usd,coalesce(f.cash_usd,0)::DECIMAL(24,2) AS pos_cash_usd
FROM raw.trips t JOIN staging.player_identity i USING(player_id)
LEFT JOIN play p USING(observed_visit_id) LEFT JOIN pos f USING(observed_visit_id);
