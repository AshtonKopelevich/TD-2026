CREATE TABLE staging.hourly_base AS
SELECT h.machine_id,h.hour_start_utc,h.gaming_date,h.local_hour::BIGINT AS local_hour,h.utc_offset,
 (h.local_hour//s.band_hours)::BIGINT AS hour_band,h.location_id AS source_location_id,
 p.placement_id,p.location_id,p.config_id,l.zone_id,l.bank_id,m.manufacturer,
 greatest(h.hour_start_utc,p.effective_from_utc,c.gaming_day_start_utc) AS installed_start,
 least(h.hour_start_utc+INTERVAL '1 hour',coalesce(p.effective_to_utc,c.gaming_day_end_utc),c.gaming_day_end_utc) AS installed_end,
 date_diff('second',installed_start,installed_end)::BIGINT AS scheduled_seconds,
 h.available_seconds,h.occupied_seconds,h.paid_spins,
 (h.coin_in_cents*0.01)::DECIMAL(24,2) AS coin_in_usd,
 (h.payout_cents*0.01)::DECIMAL(24,2) AS payout_usd,
 (h.coin_in_cents*0.01*(1-g.configured_rtp))::DECIMAL(28,8) AS theo_usd,
 d.available_seconds=d.scheduled_seconds AND f.machine_id IS NULL AND h.available_seconds=3600
   AND date_diff('second',installed_start,installed_end)=3600 AND h.gaming_date>=greatest(m.install_date,
     CASE WHEN p.effective_from_utc>(SELECT min(gaming_day_start_utc) FROM raw.calendar_day)
          THEN staging.gaming_date(p.effective_from_utc) ELSE m.install_date END)+s.stabilization_days::INTEGER AS healthy
FROM raw.machine_hour h CROSS JOIN staging.analysis_window w CROSS JOIN staging.downtime_settings s
JOIN raw.calendar_day c USING(gaming_date)
LEFT JOIN raw.placements p ON p.machine_id=h.machine_id AND p.effective_from_utc<h.hour_start_utc+INTERVAL '1 hour'
 AND coalesce(p.effective_to_utc,TIMESTAMP '9999-12-31')>h.hour_start_utc
LEFT JOIN raw.floor_locations l ON l.location_id=p.location_id
LEFT JOIN raw.machines m ON m.machine_id=h.machine_id
LEFT JOIN raw.game_math g ON g.config_id=p.config_id
LEFT JOIN marts.mart_machine_daily d ON d.machine_id=h.machine_id AND d.gaming_date=h.gaming_date
LEFT JOIN staging.fault_days f ON f.machine_id=h.machine_id AND f.gaming_date=h.gaming_date
WHERE h.gaming_date BETWEEN w.start_date AND w.end_date;

-- Sweep interval endpoints: each covered subinterval gets one priority, even
-- when several tickets overlap. Faults precede planned work; meters remain the
-- authority for total unavailable seconds.
CREATE TABLE staging.outage_overlaps AS
SELECT h.machine_id,h.hour_start_utc,o.operation_id,
 CASE WHEN o.event_type='fault_repair' THEN 1 WHEN o.event_type IN ({{planned_types}}) THEN 2 ELSE 3 END AS priority,
 greatest(h.installed_start,o.clipped_start) AS lo,least(h.installed_end,o.clipped_end) AS hi
FROM staging.hourly_base h JOIN staging.operation_intervals o ON h.machine_id=o.machine_id
 AND o.clipped_start<h.installed_end AND o.clipped_end>h.installed_start;

CREATE TABLE staging.outage_allocations AS
WITH edges AS (
 SELECT machine_id,hour_start_utc,lo AS edge FROM staging.outage_overlaps
 UNION SELECT machine_id,hour_start_utc,hi FROM staging.outage_overlaps
), spans AS (
 SELECT *,lead(edge) OVER(PARTITION BY machine_id,hour_start_utc ORDER BY edge) AS next_edge FROM edges
), classified AS (
 SELECT e.machine_id,e.hour_start_utc,e.edge,e.next_edge,min(o.priority) AS priority
 FROM spans e JOIN staging.outage_overlaps o ON o.machine_id=e.machine_id AND o.hour_start_utc=e.hour_start_utc
 AND e.edge>=o.lo AND e.next_edge<=o.hi WHERE e.next_edge>e.edge
 GROUP BY e.machine_id,e.hour_start_utc,e.edge,e.next_edge
)
SELECT machine_id,hour_start_utc,
 coalesce(sum(date_diff('second',edge,next_edge)) FILTER(WHERE priority=1),0)::BIGINT AS fault_seconds,
 coalesce(sum(date_diff('second',edge,next_edge)) FILTER(WHERE priority=2),0)::BIGINT AS planned_seconds,
 sum(date_diff('second',edge,next_edge))::BIGINT AS ticket_seconds
FROM classified GROUP BY machine_id,hour_start_utc;

CREATE TABLE staging.peer_banks AS
SELECT zone_id,bank_id,hour_start_utc,count(*) FILTER(WHERE healthy)::BIGINT AS n,
 coalesce(sum(coin_in_usd) FILTER(WHERE healthy),0)::DOUBLE AS coin,
 coalesce(sum(theo_usd) FILTER(WHERE healthy),0)::DOUBLE AS theo,
 coalesce(sum(occupied_seconds) FILTER(WHERE healthy),0)::BIGINT AS occupied
FROM staging.hourly_base GROUP BY zone_id,bank_id,hour_start_utc;

CREATE TABLE staging.hourly_peers AS
WITH zones AS (
 SELECT zone_id,hour_start_utc,sum(n) AS n,sum(coin) AS coin,sum(theo) AS theo,sum(occupied) AS occupied
 FROM staging.peer_banks GROUP BY zone_id,hour_start_utc
)
SELECT h.*,(z.n-b.n)::BIGINT AS neighbor_count,(z.n-b.n)::DOUBLE AS neighbor_available_hours,
 (z.coin-b.coin)/nullif(z.n-b.n,0) AS peer_coin_rate,
 (z.theo-b.theo)/nullif(z.n-b.n,0) AS peer_theo_rate,
 (z.occupied-b.occupied)::DOUBLE/nullif((z.n-b.n)*3600,0) AS peer_occupancy
FROM staging.hourly_base h JOIN staging.peer_banks b USING(zone_id,bank_id,hour_start_utc)
JOIN zones z USING(zone_id,hour_start_utc);

-- Daily/band aggregates keep the +/-28-day reference calculation bounded.
CREATE TABLE staging.reference_days AS
SELECT h.machine_id,h.placement_id,h.config_id,h.hour_band,h.gaming_date,
 count(*) FILTER(WHERE healthy AND neighbor_count>=s.min_peers)::BIGINT AS day_n,
 coalesce(sum(coin_in_usd) FILTER(WHERE healthy AND neighbor_count>=s.min_peers),0)::DOUBLE AS day_coin,
 coalesce(sum(theo_usd) FILTER(WHERE healthy AND neighbor_count>=s.min_peers),0)::DOUBLE AS day_theo,
 coalesce(sum(peer_coin_rate) FILTER(WHERE healthy AND neighbor_count>=s.min_peers),0)::DOUBLE AS day_peer_coin,
 coalesce(sum(peer_theo_rate) FILTER(WHERE healthy AND neighbor_count>=s.min_peers),0)::DOUBLE AS day_peer_theo
FROM staging.hourly_peers h CROSS JOIN staging.downtime_settings s
GROUP BY h.machine_id,h.placement_id,h.config_id,h.hour_band,h.gaming_date;

CREATE TABLE staging.reference_windows AS
SELECT *,sum(day_n) OVER w AS reference_n,sum(day_coin) OVER w AS reference_coin,
 sum(day_theo) OVER w AS reference_theo,sum(day_peer_coin) OVER w AS reference_peer_coin,
 sum(day_peer_theo) OVER w AS reference_peer_theo
FROM staging.reference_days
WINDOW w AS (PARTITION BY machine_id,placement_id,config_id,hour_band ORDER BY gaming_date
 RANGE BETWEEN INTERVAL '{{reference_days}} days' PRECEDING AND INTERVAL '{{reference_days}} days' FOLLOWING);

CREATE TABLE staging.hourly_reference AS
SELECT h.*,r.* EXCLUDE(machine_id,placement_id,config_id,hour_band,gaming_date)
FROM staging.hourly_peers h JOIN staging.reference_windows r
USING(machine_id,placement_id,config_id,hour_band,gaming_date);

CREATE TABLE staging.hourly_staff AS
SELECT k.zone_id,k.hour_start_utc,
 CASE WHEN count(known.gaming_date)>0 THEN coalesce(sum(
   date_diff('microsecond',greatest(r.start_utc,k.hour_start_utc),
     least(r.end_utc,k.hour_start_utc+INTERVAL '1 hour'))/3600000000.0),0) END::DOUBLE AS staff_hours
FROM (SELECT DISTINCT zone_id,hour_start_utc,gaming_date FROM staging.hourly_base) k
LEFT JOIN (SELECT DISTINCT gaming_date FROM raw.shift_roster) known USING(gaming_date)
LEFT JOIN raw.shift_roster r ON r.role='slot_tech' AND (r.zone_id=k.zone_id OR r.zone_id IS NULL)
 AND r.start_utc<k.hour_start_utc+INTERVAL '1 hour' AND r.end_utc>k.hour_start_utc
GROUP BY k.zone_id,k.hour_start_utc;
