"""Two targeted stage-five checks; no complete earlier-stage rebuilds."""

from decimal import Decimal

from casino_pipeline import constants as c
from casino_pipeline.analysis.downtime import build_downtime,validate_downtime,validate_inputs


def seed(con,monkeypatch,partial=False):
    monkeypatch.setattr(c,'MIN_HEALTHY_MATCHED_HOURS',2)
    monkeypatch.setattr(c,'DOWNTIME_MIN_VALIDATION_CASES',1)
    monkeypatch.setattr(c,'DOWNTIME_VALIDATION_SAMPLE_SIZE',500)
    monkeypatch.setattr(c,'BUSY_PEER_THRESHOLD',0.4)
    con.execute("""
    CREATE TABLE staging.analysis_window AS SELECT DATE '2025-01-01' AS start_date,DATE '2025-01-03' AS end_date;
    CREATE MACRO staging.gaming_date(ts) AS cast(ts-INTERVAL '14 hours' AS DATE);
    CREATE TABLE raw.calendar_day AS SELECT d::DATE AS gaming_date,d+INTERVAL '14 hours' AS gaming_day_start_utc,
      d+INTERVAL '38 hours' AS gaming_day_end_utc FROM generate_series(
      TIMESTAMP '2025-01-01',TIMESTAMP '2025-01-03',INTERVAL '1 day') days(d);
    CREATE TABLE raw.machines AS SELECT 'M'||i AS machine_id,'Maker'::VARCHAR AS manufacturer,
      DATE '2020-01-01' AS install_date FROM range(4) r(i);
    CREATE TABLE raw.floor_locations AS SELECT 'L'||i AS location_id,'Z'::VARCHAR AS zone_id,
      'B'||i AS bank_id FROM range(4) r(i);
    CREATE TABLE raw.placements AS SELECT 'P'||i AS placement_id,'M'||i AS machine_id,'L'||i AS location_id,
      'C1'::VARCHAR AS config_id,TIMESTAMP '2025-01-01 14:00:00' AS effective_from_utc,
      NULL::TIMESTAMP AS effective_to_utc FROM range(4) r(i);
    CREATE TABLE raw.game_math AS SELECT 'C1'::VARCHAR AS config_id,0.90::DECIMAL(10,8) AS configured_rtp;
    CREATE TABLE raw.operations (operation_id VARCHAR,machine_id VARCHAR,location_id VARCHAR,event_type VARCHAR,
      opened_at_utc TIMESTAMP,recorded_at_utc TIMESTAMP,work_started_at_utc TIMESTAMP,available_at_utc TIMESTAMP,direct_cost_cents BIGINT);
    INSERT INTO raw.operations VALUES
      ('O1','M0','L0','scheduled_maintenance','2025-01-02 18:00:00','2025-01-02 18:00:00','2025-01-02 18:00:00','2025-01-02 19:00:00',0),
      ('O2','M0','L0','fault_repair','2025-01-02 18:15:00','2025-01-02 18:15:00','2025-01-02 18:20:00','2025-01-02 18:45:00',1200),
      ('O3','M0','L0','fault_repair','2025-01-02 18:30:00','2025-01-02 18:30:00','2025-01-02 18:35:00','2025-01-02 18:50:00',1000);
    CREATE TABLE raw.machine_hour AS WITH base AS (
      SELECT 'M'||i AS machine_id,'L'||i AS location_id,c.gaming_date,
        c.gaming_day_start_utc+j*INTERVAL '1 hour' AS hour_start_utc,
        hour(hour_start_utc-INTERVAL '8 hours')::INTEGER AS local_hour,'-08:00'::VARCHAR AS utc_offset,
        true AS active,(i=0 AND hour_start_utc=TIMESTAMP '2025-01-02 18:00:00') AS outage,
        (i=0 AND hour_start_utc BETWEEN TIMESTAMP '2025-01-04 04:00:00' AND TIMESTAMP '2025-01-04 06:00:00') AS hidden,
        CASE WHEN outage OR hidden THEN 0 WHEN i=0 THEN 10000 ELSE 5000 END::BIGINT AS coin_in_cents
      FROM range(4) machines(i) CROSS JOIN raw.calendar_day c CROSS JOIN range(24) hours(j)
    ) SELECT * EXCLUDE(outage,hidden),CASE WHEN outage THEN 0 ELSE 3600 END::BIGINT AS available_seconds,
      CASE WHEN outage OR hidden THEN 0 ELSE 1800 END::BIGINT AS occupied_seconds,
      (coin_in_cents//100)::BIGINT AS paid_spins,(coin_in_cents*0.9)::BIGINT AS payout_cents FROM base;
    CREATE TABLE raw.shift_roster AS SELECT gaming_date::VARCHAR AS assignment_id,gaming_date,
      'slot_tech'::VARCHAR AS role,NULL::VARCHAR AS zone_id,gaming_day_start_utc AS start_utc,gaming_day_end_utc AS end_utc
      FROM raw.calendar_day;
    """)
    if partial:
        con.execute("UPDATE raw.placements SET effective_from_utc=TIMESTAMP '2025-01-01 14:30:00' WHERE machine_id='M0'")
        con.execute("""UPDATE raw.machine_hour SET available_seconds=1800,occupied_seconds=900
          WHERE machine_id='M0' AND hour_start_utc=TIMESTAMP '2025-01-01 14:00:00'""")
    con.execute("""CREATE TABLE marts.mart_machine_daily AS
      SELECT h.machine_id,h.gaming_date,h.location_id,'C1'::VARCHAR AS config_id,
      sum(date_diff('second',greatest(h.hour_start_utc,p.effective_from_utc),h.hour_start_utc+INTERVAL '1 hour'))::BIGINT AS scheduled_seconds,
      sum(available_seconds)::BIGINT AS available_seconds,sum(occupied_seconds)::BIGINT AS occupied_seconds,
      sum(coin_in_cents*0.01)::DECIMAL(24,2) AS coin_in_usd,sum(payout_cents*0.01)::DECIMAL(24,2) AS payout_usd,
      sum(coin_in_cents*0.001)::DECIMAL(28,8) AS theo_usd
      FROM raw.machine_hour h JOIN raw.placements p USING(machine_id) GROUP BY h.machine_id,h.gaming_date,h.location_id""")


def test_interval_union_peer_estimate_staff_and_fake_outage_validation(connection,monkeypatch):
    seed(connection,monkeypatch)
    assert all(check['passed'] for check in validate_inputs(connection))
    build_downtime(connection)
    assert not [check for check in validate_downtime(connection) if not check['passed']]
    outage = connection.execute("""SELECT downtime_seconds,fault_downtime_seconds,planned_downtime_seconds,
      ticket_overlap_seconds,neighbor_count,usual_rate_ratio,estimated_lost_theo_usd,available_tech_staff_hours
      FROM marts.mart_downtime_hourly WHERE machine_id='M0' AND hour_start_utc=TIMESTAMP '2025-01-02 18:00:00'""").fetchone()
    assert outage==(3600,2100,1500,3600,3,2.0,Decimal('10.00000000'),1.0)
    assert connection.execute('SELECT count(*) FROM marts.mart_tickets').fetchone()[0]==3
    assert connection.execute('SELECT count(*) FROM marts.mart_downtime_hourly WHERE hidden_downtime_flag').fetchone()[0]==3
    assert connection.execute('SELECT count(*) FROM diagnostics.downtime_validation_cases').fetchone()[0]>0
    ticket = connection.execute("SELECT total_outage_hours,direct_cost_usd,comparison_status FROM marts.mart_tickets WHERE operation_id='O2'").fetchone()
    assert ticket==(0.5,Decimal('12.00'),'truncated_window')


def test_partial_install_and_insufficient_peers_stay_explicit(connection,monkeypatch):
    seed(connection,monkeypatch,partial=True)
    monkeypatch.setattr(c,'MIN_OTHER_BANK_PEERS',4)
    monkeypatch.setattr(c,'BUSY_PEER_THRESHOLD',None)
    build_downtime(connection)
    assert all(check['passed'] for check in validate_downtime(connection))
    assert connection.execute("""SELECT scheduled_seconds,available_seconds,downtime_seconds
      FROM marts.mart_downtime_hourly WHERE machine_id='M0' AND hour_start_utc=TIMESTAMP '2025-01-01 14:00:00'""").fetchone()==(1800,1800,0)
    assert connection.execute("""SELECT estimate_status,estimated_lost_theo_usd,hidden_downtime_flag
      FROM marts.mart_downtime_hourly WHERE downtime_seconds>0""").fetchone()==('insufficient_peers',None,None)
