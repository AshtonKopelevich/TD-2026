CREATE TABLE staging.operation_intervals AS
SELECT o.*,staging.gaming_date(o.opened_at_utc) AS gaming_date,
 staging.gaming_date(o.available_at_utc) AS restored_gaming_date,
 greatest(o.opened_at_utc,b.start_utc) AS clipped_start,
 least(coalesce(o.available_at_utc,b.end_utc),b.end_utc) AS clipped_end
FROM raw.operations o CROSS JOIN (
 SELECT min(c.gaming_day_start_utc) AS start_utc,max(c.gaming_day_end_utc) AS end_utc
 FROM raw.calendar_day c CROSS JOIN staging.analysis_window w WHERE c.gaming_date BETWEEN w.start_date AND w.end_date
) b WHERE o.opened_at_utc<b.end_utc AND coalesce(o.available_at_utc,b.end_utc)>=b.start_utc;

CREATE TABLE staging.fault_days AS
SELECT DISTINCT o.machine_id,c.gaming_date FROM staging.operation_intervals o JOIN raw.calendar_day c
 ON o.clipped_start<c.gaming_day_end_utc AND o.clipped_end>c.gaming_day_start_utc
WHERE o.event_type='fault_repair';
