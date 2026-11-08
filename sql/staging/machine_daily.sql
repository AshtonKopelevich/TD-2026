-- Daily peer pools exclude the target and require positive available exposure.
CREATE TABLE staging.machine_peer_day AS
WITH zones AS (
 SELECT zone_id,gaming_date,count(*) FILTER(WHERE available_seconds>0)::BIGINT AS n,
 coalesce(sum(available_seconds) FILTER(WHERE available_seconds>0),0)::DOUBLE/3600 AS hours,
 coalesce(sum(coin_in_usd) FILTER(WHERE available_seconds>0),0)::DOUBLE AS coin,
 coalesce(sum(theo_usd) FILTER(WHERE available_seconds>0),0)::DOUBLE AS theo,
 coalesce(sum(expected_contribution_usd) FILTER(WHERE available_seconds>0),0)::DOUBLE AS contribution
 FROM marts.mart_machine_daily GROUP BY zone_id,gaming_date
), floor AS (
 SELECT gaming_date,sum(n) AS n,sum(hours) AS hours,sum(coin) AS coin FROM zones GROUP BY gaming_date
), banks AS (
 SELECT bank_id,gaming_date,count(*) FILTER(WHERE available_seconds>0)::BIGINT AS n,
 coalesce(sum(available_seconds) FILTER(WHERE available_seconds>0),0)::DOUBLE/3600 AS hours,
 coalesce(sum(theo_usd) FILTER(WHERE available_seconds>0),0)::DOUBLE AS theo
 FROM marts.mart_machine_daily GROUP BY bank_id,gaming_date
), targets AS (
 SELECT d.*,d.available_seconds/3600.0 AS target_hours,
 CASE WHEN d.available_seconds>0 THEN 1 ELSE 0 END AS self_n,
 CASE WHEN d.available_seconds>0 THEN d.coin_in_usd ELSE 0 END::DOUBLE AS self_coin,
 CASE WHEN d.available_seconds>0 THEN d.theo_usd ELSE 0 END::DOUBLE AS self_theo,
 CASE WHEN d.available_seconds>0 THEN d.expected_contribution_usd ELSE 0 END::DOUBLE AS self_contribution
 FROM marts.mart_machine_daily d
)
SELECT d.machine_id,d.gaming_date,d.zone_id,d.bank_id,d.config_id,d.target_hours,
 d.coin_in_usd,d.theo_usd,(z.n-d.self_n)::BIGINT AS peer_count,
 (z.theo-d.self_theo)/nullif(z.hours-d.target_hours,0) AS peer_theo_rate,
 (z.coin-d.self_coin)/nullif(z.hours-d.target_hours,0) AS peer_coin_rate,
 (z.contribution-d.self_contribution)/nullif(z.hours-d.target_hours,0) AS peer_contribution_rate,
 (f.coin-d.self_coin)/nullif(f.hours-d.target_hours,0) AS floor_coin_rate,
 (b.n-d.self_n)::BIGINT AS bank_peer_count,
 (b.theo-d.self_theo)/nullif(b.hours-d.target_hours,0) AS bank_peer_theo_rate
FROM targets d JOIN zones z USING(zone_id,gaming_date) JOIN floor f USING(gaming_date)
JOIN banks b USING(bank_id,gaming_date);

CREATE TABLE diagnostics.machine_bank_comparisons AS
SELECT machine_id,gaming_date,bank_id,bank_peer_count,bank_peer_theo_rate FROM staging.machine_peer_day;

CREATE TABLE diagnostics.machine_placement_summary AS
SELECT p.placement_id,d.machine_id,d.location_id,d.zone_id,d.bank_id,d.config_id,
 min(d.gaming_date) AS first_active_date,max(d.gaming_date) AS last_active_date,
 count(*)::BIGINT AS active_days,sum(d.available_seconds)/3600.0 AS available_hours,
 sum(d.coin_in_usd)::DOUBLE/nullif(sum(d.available_seconds)/3600.0,0) AS coin_in_per_available_hour,
 sum(d.theo_usd)::DOUBLE/nullif(sum(d.available_seconds)/3600.0,0) AS theo_per_available_hour
FROM marts.mart_machine_daily d JOIN raw.calendar_day c USING(gaming_date)
JOIN raw.placements p ON p.machine_id=d.machine_id AND p.effective_from_utc<c.gaming_day_end_utc
 AND coalesce(p.effective_to_utc,TIMESTAMP '9999-12-31')>c.gaming_day_start_utc
GROUP BY p.placement_id,d.machine_id,d.location_id,d.zone_id,d.bank_id,d.config_id;
