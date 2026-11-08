-- All-play meters retain precision; prepared cost components are authoritative.
CREATE TABLE marts.mart_machine_daily AS
WITH base AS (
    SELECT d.machine_id, d.gaming_date,
        date_trunc('month', d.gaming_date)::DATE AS month_start,
        d.location_id, l.zone_id, l.bank_id, d.config_id, p.zone_name,
        machines.manufacturer, g.theme, machines.lease_class,
        l.x_m, l.y_m, d.active, d.meter_status,
        g.configured_rtp::DOUBLE AS configured_rtp, g.volatility_class,
        g.payout_multiplier_variance::DOUBLE AS payout_multiplier_variance,
        d.scheduled_seconds, d.available_seconds, d.occupied_seconds,
        c.scheduled_seconds AS calendar_day_seconds, d.paid_spins, d.carded_spins,
        (d.coin_in_cents * 0.01)::DECIMAL(24,2) AS coin_in_usd,
        (d.payout_cents * 0.01)::DECIMAL(24,2) AS payout_usd,
        (d.house_win_cents * 0.01)::DECIMAL(24,2) AS house_win_usd,
        (d.carded_coin_in_cents * 0.01)::DECIMAL(24,2) AS carded_coin_in_usd,
        (d.carded_payout_cents * 0.01)::DECIMAL(24,2) AS carded_payout_usd,
        (d.theo_cents * 0.01)::DECIMAL(28,8) AS theo_usd,
        (d.carded_theo_cents * 0.01)::DECIMAL(28,8) AS carded_theo_usd,
        p.lease_cost_usd::DECIMAL(24,2) AS lease_cost_usd,
        p.service_cost_usd::DECIMAL(24,2) AS service_cost_usd,
        p.power_cost_usd::DECIMAL(24,2) AS power_cost_usd,
        p.repair_cost_usd::DECIMAL(24,2) AS repair_cost_usd,
        p.faults_opened::BIGINT AS faults_opened,
        d.sum_bet_squared AS sum_bet_squared_cents2,
        g.payout_multiplier_variance::DOUBLE * d.sum_bet_squared / 10000.0 AS outcome_variance_usd2
    FROM raw.machine_day d CROSS JOIN staging.analysis_window w
    LEFT JOIN raw.prepared_daily_view p USING(machine_id, gaming_date)
    LEFT JOIN raw.calendar_day c USING(gaming_date)
    LEFT JOIN raw.machines machines USING(machine_id)
    LEFT JOIN raw.floor_locations l ON d.location_id = l.location_id
    LEFT JOIN raw.game_math g ON d.config_id = g.config_id
    WHERE d.active AND d.gaming_date BETWEEN w.start_date AND w.end_date
), costs AS (
    SELECT *, (lease_cost_usd + service_cost_usd + power_cost_usd + repair_cost_usd)::DECIMAL(24,2) AS machine_cost_usd
    FROM base
), measures AS (
    SELECT *, (house_win_usd - machine_cost_usd)::DECIMAL(24,2) AS actual_contribution_usd,
        (theo_usd - machine_cost_usd)::DECIMAL(28,8) AS expected_contribution_usd,
        (house_win_usd - theo_usd)::DECIMAL(28,8) AS luck_residual_usd
    FROM costs
)
SELECT *, available_seconds::DOUBLE / nullif(scheduled_seconds,0) AS availability_ratio,
    occupied_seconds::DOUBLE / nullif(available_seconds,0) AS occupancy_ratio,
    house_win_usd::DOUBLE / nullif(coin_in_usd,0) AS observed_hold,
    theo_usd::DOUBLE / nullif(coin_in_usd,0) AS expected_hold,
    carded_coin_in_usd::DOUBLE / nullif(coin_in_usd,0) AS carded_coin_in_share,
    coin_in_usd::DOUBLE / nullif(available_seconds / 3600.0,0) AS coin_in_per_available_hour,
    theo_usd::DOUBLE / nullif(available_seconds / 3600.0,0) AS theo_per_available_hour,
    expected_contribution_usd::DOUBLE / nullif(available_seconds / 3600.0,0) AS expected_contribution_per_available_hour
FROM measures ORDER BY machine_id, gaming_date;
