CREATE TABLE marts.mart_benchmark_month AS
WITH property AS (
 SELECT month_start,sum(coin_in_usd)::DECIMAL(24,2) AS property_coin_in_usd,
 sum(house_win_usd)::DECIMAL(24,2) AS property_house_win_usd,
 sum(active_machines)::BIGINT AS property_active_machine_days,count(*)::BIGINT AS property_observed_days,
 count(*)=day(last_day(month_start)) AS property_period_complete
 FROM marts.mart_floor_daily GROUP BY month_start
), base AS (
 SELECT p.*,make_date(year(p.month_start),1,1) AS index_base_month,
 p.property_coin_in_usd::DOUBLE/nullif(p.property_active_machine_days,0) AS property_coin_in_per_machine_day,
 m.handle_usd::DECIMAL(24,2) AS missouri_coin_in_usd,m.agr_usd::DECIMAL(24,2) AS missouri_house_win_usd,
 v.visitor_volume::BIGINT AS las_vegas_visitor_volume,
 CASE WHEN p.property_period_complete AND jan.property_period_complete
      THEN p.property_coin_in_usd::DOUBLE/nullif(jan.property_coin_in_usd,0)*100 END AS property_coin_in_index,
 m.handle_usd::DOUBLE/nullif(mjan.handle_usd,0)*100 AS missouri_coin_in_index,
 v.visitor_volume::DOUBLE/nullif(vjan.visitor_volume,0)*100 AS las_vegas_visitors_index,
 CASE WHEN m.month IS NULL THEN 'missing' WHEN m.handle_usd IS NULL OR m.agr_usd IS NULL THEN 'partial' ELSE 'complete' END AS missouri_status,
 CASE WHEN v.month IS NULL THEN 'missing' WHEN v.visitor_volume IS NULL THEN 'partial' ELSE 'complete' END AS visitation_status,
 m.source_url AS missouri_source_url,v.source_url AS visitation_source_url,
 v.source_revision,v.as_of_limitation,m.retrieved_date AS missouri_retrieved_date
 FROM property p
 LEFT JOIN property jan ON jan.month_start=make_date(year(p.month_start),1,1)
 LEFT JOIN raw.benchmark_state_monthly m ON try_cast(m.month||'-01' AS DATE)=p.month_start
 LEFT JOIN raw.city_visitation_monthly v ON try_cast(v.month||'-01' AS DATE)=p.month_start
 LEFT JOIN raw.benchmark_state_monthly mjan ON mjan.month=year(p.month_start)::VARCHAR||'-01'
 LEFT JOIN raw.city_visitation_monthly vjan ON vjan.month=year(p.month_start)::VARCHAR||'-01'
)
SELECT * FROM base ORDER BY month_start;
