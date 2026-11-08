CREATE TABLE marts.mart_floor_daily AS
WITH machines AS (
 SELECT gaming_date,count(*)::BIGINT AS active_machines,
 sum(scheduled_seconds)/3600.0 AS scheduled_machine_hours,
 sum(available_seconds)/3600.0 AS available_machine_hours,
 sum(occupied_seconds)/3600.0 AS occupied_machine_hours,
 sum(coin_in_usd)::DECIMAL(24,2) AS coin_in_usd, sum(payout_usd)::DECIMAL(24,2) AS payout_usd,
 sum(house_win_usd)::DECIMAL(24,2) AS house_win_usd,
 sum(theo_usd)::DECIMAL(28,8) AS theo_usd, sum(carded_coin_in_usd)::DECIMAL(24,2) AS carded_coin_in_usd,
 sum(machine_cost_usd)::DECIMAL(24,2) AS machine_cost_usd
 FROM marts.mart_machine_daily GROUP BY gaming_date
), base AS (
 SELECT c.gaming_date,date_trunc('month',c.gaming_date)::DATE AS month_start,
 (isodow(c.gaming_date)-1)::BIGINT AS weekday_index, isodow(c.gaming_date) IN (6,7) AS is_weekend,
 nullif(c.federal_holiday,'') AS federal_holiday,e.events_active,
 coalesce(m.active_machines,0)::BIGINT AS active_machines,
 coalesce(m.scheduled_machine_hours,0)::DOUBLE AS scheduled_machine_hours,
 coalesce(m.available_machine_hours,0)::DOUBLE AS available_machine_hours,
 coalesce(m.occupied_machine_hours,0)::DOUBLE AS occupied_machine_hours,
 coalesce(m.coin_in_usd,0)::DECIMAL(24,2) AS coin_in_usd,
 coalesce(m.payout_usd,0)::DECIMAL(24,2) AS payout_usd,
 coalesce(m.house_win_usd,0)::DECIMAL(24,2) AS house_win_usd,
 coalesce(m.theo_usd,0)::DECIMAL(28,8) AS theo_usd,
 coalesce(m.carded_coin_in_usd,0)::DECIMAL(24,2) AS carded_coin_in_usd,
 p.pos_cash_usd::DECIMAL(24,2) AS pos_cash_usd,p.pos_cogs_usd::DECIMAL(24,2) AS pos_cogs_usd,
 p.comp_cost_usd::DECIMAL(24,2) AS comp_cost_usd,
 coalesce(m.machine_cost_usd,0)::DECIMAL(24,2) AS machine_cost_usd,
 p.tech_labor_cost_usd::DECIMAL(24,2) AS tech_labor_cost_usd,
 w.tmax_c AS weather_temperature_max_c,w.prcp_mm AS weather_precipitation_mm,
 w.trace AS weather_precipitation_trace,coalesce(w.weather_status,'missing') AS weather_status
 FROM raw.calendar_day c CROSS JOIN staging.analysis_window limits
 LEFT JOIN machines m USING(gaming_date) LEFT JOIN raw.property_day p USING(gaming_date)
 LEFT JOIN staging.events_daily e USING(gaming_date) LEFT JOIN staging.weather_daily w ON w.source_date=c.gaming_date
 WHERE c.gaming_date BETWEEN limits.start_date AND limits.end_date
)
SELECT *,carded_coin_in_usd::DOUBLE/nullif(coin_in_usd,0) AS carded_coin_in_share,
 coin_in_usd::DOUBLE/nullif(active_machines,0) AS coin_in_per_active_machine_day,
 (house_win_usd+pos_cash_usd-pos_cogs_usd-machine_cost_usd-tech_labor_cost_usd)::DECIMAL(24,2) AS actual_floor_contribution_usd
FROM base ORDER BY gaming_date;
