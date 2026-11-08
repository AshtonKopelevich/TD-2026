-- Parameters: first historical date, forecast end, selected method (twice).
-- Predictions are already frozen; targets join only for display/evaluation.
CREATE TABLE marts.mart_forecast AS
WITH dates AS (
 SELECT d::DATE AS forecast_date FROM generate_series(?::TIMESTAMP,?::TIMESTAMP,INTERVAL '1 day') t(d)
)
SELECT d.forecast_date,coalesce(f.split,'train') AS split,a.coin_in_usd::DECIMAL(24,2) AS actual_coin_in_usd,
 f.model_prediction_usd,f.baseline_prediction_usd,?::VARCHAR AS model_method,
 f.fit_start,f.fit_end,f.forecast_origin,f.prediction_frozen_at_utc,
 coalesce(f.split IN ('validation','test'),false) AS evaluation_eligible,
 (isodow(d.forecast_date)-1)::BIGINT AS weekday_index
FROM dates d LEFT JOIN diagnostics.forecast_frozen_predictions f
 ON f.forecast_date=d.forecast_date AND f.model_method=?
LEFT JOIN marts.mart_floor_daily a ON a.gaming_date=d.forecast_date
ORDER BY d.forecast_date;
