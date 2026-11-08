"""Known-answer descriptive marts: no dependency on the full source release."""

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from casino_pipeline import build
from casino_pipeline.descriptive import build_descriptive, validate_descriptive, validate_inputs
from casino_pipeline.machine_daily import build_machine_daily
from test_machine_daily import create_machine_sources


def create_descriptive_sources(con):
    create_machine_sources(con)
    con.execute("""
      ALTER TABLE raw.calendar_day ADD COLUMN federal_holiday VARCHAR;
      ALTER TABLE raw.floor_locations ADD COLUMN name VARCHAR;
      UPDATE raw.floor_locations SET name=location_id;
      INSERT INTO raw.floor_locations VALUES
        ('Z1','Z1',NULL,0,0,'zone','First zone'),
        ('Z2','Z2',NULL,0,0,'zone','Second zone'),
        ('Z3','Z3',NULL,0,0,'zone','Empty zone'),
        ('L3','Z3','B3',0,0,'slot','Unused slot');
      CREATE TABLE raw.property_day AS SELECT d.gaming_date,count(*)::BIGINT AS active_machines,
        sum(d.available_seconds)/3600.0 AS available_machine_hours,
        sum(d.occupied_seconds)/3600.0 AS occupied_machine_hours,
        sum(d.coin_in_cents)*0.01 AS coin_in_usd,sum(d.payout_cents)*0.01 AS payout_usd,
        sum(d.house_win_cents)*0.01 AS house_win_usd,sum(d.theo_cents)*0.01 AS theo_usd,
        count(*)*10.0 AS machine_supplied_costs_usd,7.0 AS tech_labor_cost_usd,
        100.0 AS pos_cash_usd,20.0 AS pos_cogs_usd,3.0 AS comp_cost_usd,
        sum(d.house_win_cents)*0.01+100-20-count(*)*10-7 AS contribution_after_supplied_costs_usd
        FROM raw.machine_day d WHERE active GROUP BY gaming_date;
      CREATE TABLE raw.events (event_id VARCHAR,name VARCHAR,start_date DATE,end_date DATE);
      INSERT INTO raw.events VALUES ('E2','Second event','2025-03-08','2025-03-08'),
        ('E1','First event','2025-03-08','2025-03-08');
      CREATE TABLE raw.weather_daily (station_id VARCHAR,source_date DATE,tmax_c DECIMAL(8,1),
        prcp_mm DECIMAL(8,1),tmax_qflag VARCHAR,prcp_qflag VARCHAR,prcp_mflag VARCHAR);
      INSERT INTO raw.weather_daily VALUES
        ('USW00023169','2025-03-08',30,0,'','','T'),
        ('USW00023169','2025-03-09',31,2,'X','','');
      CREATE TABLE raw.zone_traffic_hourly (sensor_id VARCHAR,zone_id VARCHAR,hour_start_utc TIMESTAMP,
        entries_count BIGINT,counter_status VARCHAR,coverage_minutes INTEGER);
      INSERT INTO raw.zone_traffic_hourly SELECT 'S1','Z1',
        TIMESTAMP '2025-03-08 14:00:00'+i*INTERVAL '1 hour',100,'ok',60 FROM range(23) r(i);
      -- One missing feed hour on day 2 must not shrink expected coverage.
      INSERT INTO raw.zone_traffic_hourly SELECT 'S1','Z1',
        TIMESTAMP '2025-03-09 13:00:00'+i*INTERVAL '1 hour',100,'ok',60 FROM range(23) r(i);
      INSERT INTO raw.zone_traffic_hourly SELECT s,'Z2',
        TIMESTAMP '2025-03-08 14:00:00'+i*INTERVAL '1 hour',NULL,'offline',0
        FROM range(23) r(i) CROSS JOIN (VALUES ('S2'),('S3')) sensors(s);
      INSERT INTO raw.zone_traffic_hourly SELECT s,'Z2',
        TIMESTAMP '2025-03-09 13:00:00'+i*INTERVAL '1 hour',10,'partial',30
        FROM range(24) r(i) CROSS JOIN (VALUES ('S2'),('S3')) sensors(s);
      CREATE TABLE raw.benchmark_state_monthly (month VARCHAR,handle_usd DECIMAL(24,2),
        agr_usd DECIMAL(24,2),source_url VARCHAR,retrieved_date DATE);
      INSERT INTO raw.benchmark_state_monthly VALUES
        ('2025-01',5000,500,'https://example.com/missouri','2026-01-01'),
        ('2025-03',10000,1000,'https://example.com/missouri','2026-01-01');
      CREATE TABLE raw.city_visitation_monthly (month VARCHAR,visitor_volume BIGINT,
        source_url VARCHAR,source_revision VARCHAR,as_of_limitation VARCHAR);
      INSERT INTO raw.city_visitation_monthly VALUES
        ('2025-01',100,'https://example.com/visitors','2026-08-20','Retrospective context'),
        ('2025-03',2000,'https://example.com/visitors','2026-08-20','Retrospective context');
    """)


@pytest.fixture
def descriptive_connection(connection):
    create_descriptive_sources(connection)
    build_machine_daily(connection)
    connection.execute("UPDATE staging.analysis_window SET start_date='2025-03-08',end_date='2025-03-09'")
    return connection


def test_known_answers_and_contract_checks(descriptive_connection):
    con = descriptive_connection
    assert all(c['passed'] for c in validate_inputs(con))
    build_descriptive(con)
    failures = [c for c in validate_descriptive(con) if not c['passed']]
    assert not failures
    month = con.execute("""SELECT active_days,location_count,config_count,coin_in_usd,
        availability_ratio,observed_hold,luck_z_score,statistical_status
        FROM marts.mart_machine_month WHERE machine_id='M1'""").fetchone()
    assert month[:4] == (2,2,2,Decimal('100.00'))
    assert month[4] == pytest.approx(82800/169200)
    assert month[4] != 0.5  # Mean of daily availability ratios would be wrong.
    assert month[5:] == (0.1,None,'not_implemented')
    floor = con.execute("""SELECT active_machines,coin_in_usd,actual_floor_contribution_usd,
        events_active,weather_temperature_max_c,weather_precipitation_trace
        FROM marts.mart_floor_daily WHERE gaming_date='2025-03-08'""").fetchone()
    assert floor == (2,Decimal('200.00'),Decimal('43.00'),'First event | Second event',30.0,True)
    flagged = con.execute("""SELECT weather_status,weather_temperature_max_c,weather_precipitation_mm
        FROM marts.mart_floor_daily WHERE gaming_date='2025-03-09'""").fetchone()
    assert flagged == ('quality_flagged',None,2.0)
    benchmark = con.execute("""SELECT property_coin_in_usd,property_active_machine_days,
        property_period_complete,property_coin_in_index,missouri_coin_in_usd,missouri_coin_in_index,
        las_vegas_visitors_index FROM marts.mart_benchmark_month""").fetchone()
    assert benchmark == (Decimal('200.00'),3,False,None,Decimal('10000.00'),200.0,2000.0)


def test_traffic_dst_missing_partial_offline_and_no_sensor(descriptive_connection):
    con = descriptive_connection
    build_descriptive(con)
    rows = con.execute("""SELECT zone_id,gaming_date::VARCHAR,entries_observed,counter_expected_seconds,
        counter_observed_seconds,counter_missing_seconds,counter_coverage_ratio,traffic_status
        FROM marts.mart_zone_daily ORDER BY zone_id,gaming_date""").fetchall()
    assert rows[0] == ('Z1','2025-03-08',2300,82800,82800,0,1.0,'complete')
    assert rows[1][:6] == ('Z1','2025-03-09',2300,86400,82800,3600)
    assert rows[1][-1] == 'partial'
    assert rows[2] == ('Z2','2025-03-08',None,165600,0,0,0.0,'offline')
    assert rows[3] == ('Z2','2025-03-09',480,172800,86400,0,0.5,'partial')
    assert rows[4] == ('Z3','2025-03-08',None,0,0,0,None,'no_sensor')
    assert con.execute("""SELECT active_machines,coin_in_usd,coin_in_per_available_hour
        FROM marts.mart_zone_daily WHERE zone_id='Z3' LIMIT 1""").fetchone() == (0,Decimal('0.00'),None)


def test_missing_context_does_not_zero_fill_or_shrink_roster(descriptive_connection):
    con = descriptive_connection
    con.execute("DELETE FROM raw.weather_daily WHERE source_date='2025-03-09'")
    con.execute("DELETE FROM raw.benchmark_state_monthly WHERE month='2025-03'")
    con.execute("DELETE FROM raw.city_visitation_monthly WHERE month='2025-03'")
    con.execute("DELETE FROM raw.zone_traffic_hourly WHERE sensor_id='S1' AND hour_start_utc>=TIMESTAMP '2025-03-09 13:00:00'")
    build_descriptive(con)
    assert all(c['passed'] for c in validate_descriptive(con))
    assert con.execute("""SELECT weather_status,weather_temperature_max_c FROM marts.mart_floor_daily
        WHERE gaming_date='2025-03-09'""").fetchone() == ('missing',None)
    assert con.execute("""SELECT missouri_status,visitation_status,missouri_coin_in_usd,las_vegas_visitor_volume
        FROM marts.mart_benchmark_month""").fetchone() == ('missing','missing',None,None)
    assert con.execute("""SELECT traffic_status,counter_expected_seconds,counter_missing_seconds,entries_observed
        FROM marts.mart_zone_daily WHERE zone_id='Z1' AND gaming_date='2025-03-09'""").fetchone() == ('missing',86400,86400,None)


@pytest.mark.parametrize('mutation,expected', [
    ("INSERT INTO raw.weather_daily SELECT * FROM raw.weather_daily LIMIT 1", 'weather_daily.context_key'),
    ("INSERT INTO raw.benchmark_state_monthly SELECT * FROM raw.benchmark_state_monthly LIMIT 1", 'benchmark_state_monthly.context_key'),
    ("UPDATE raw.zone_traffic_hourly SET coverage_minutes=61 WHERE sensor_id='S1'", 'traffic.valid_observations'),
    ("UPDATE raw.zone_traffic_hourly SET entries_count=1 WHERE counter_status='offline'", 'traffic.valid_observations'),
    ("UPDATE raw.zone_traffic_hourly SET zone_id='Z3' WHERE sensor_id='S1' AND hour_start_utc=TIMESTAMP '2025-03-08 14:00:00'", 'traffic.stable_sensor_zone'),
    ("UPDATE raw.city_visitation_monthly SET month='2025-13' WHERE month='2025-03'", 'context.valid_month_keys'),
])
def test_ambiguous_or_invalid_inputs_fail(descriptive_connection, mutation, expected):
    con = descriptive_connection
    con.execute(mutation)
    checks = {c['check']: c for c in validate_inputs(con)}
    assert not checks[expected]['passed']


def test_zero_january_baselines_do_not_fall_back_to_other_months(descriptive_connection):
    con = descriptive_connection
    con.execute("UPDATE raw.benchmark_state_monthly SET handle_usd=0 WHERE month='2025-01'")
    con.execute("UPDATE raw.city_visitation_monthly SET visitor_volume=0 WHERE month='2025-01'")
    build_descriptive(con)
    assert con.execute("""SELECT missouri_coin_in_index,las_vegas_visitors_index
        FROM marts.mart_benchmark_month""").fetchone() == (None,None)


def test_complete_january_property_index_uses_full_month_total(descriptive_connection):
    con = descriptive_connection
    build_descriptive(con)
    con.execute("""CREATE TEMP TABLE january_seed AS SELECT * FROM marts.mart_floor_daily
        WHERE gaming_date='2025-03-08';
        INSERT INTO marts.mart_floor_daily SELECT january_seed.* REPLACE (d::DATE AS gaming_date,
          DATE '2025-01-01' AS month_start) FROM january_seed CROSS JOIN
          generate_series(TIMESTAMP '2025-01-01',TIMESTAMP '2025-01-31',INTERVAL '1 day') days(d);
        DROP TABLE marts.mart_benchmark_month;
    """)
    sql = Path(__file__).resolve().parents[1]/'sql'/'marts'/'benchmark_month.sql'
    con.execute(sql.read_text())
    assert con.execute("""SELECT property_coin_in_usd,property_observed_days,
        property_period_complete,property_coin_in_index,missouri_coin_in_index,las_vegas_visitors_index
        FROM marts.mart_benchmark_month WHERE month_start='2025-01-01'""").fetchone() == (
            Decimal('6200.00'),31,True,100.0,100.0,100.0)


def test_month_with_zero_wagers_has_null_hold(descriptive_connection):
    con = descriptive_connection
    # Only the existing zero-play M1 day remains in this known-answer monthly input.
    con.execute("DELETE FROM marts.mart_machine_daily WHERE gaming_date='2025-03-08'")
    build_descriptive(con)
    assert con.execute("""SELECT coin_in_usd,observed_hold,theo_per_available_hour,
        expected_contribution_usd FROM marts.mart_machine_month""").fetchone() == (
            Decimal('0.00'),None,None,Decimal('-10.00000000'))


def test_source_contribution_must_include_labor_once(descriptive_connection):
    con = descriptive_connection
    con.execute('UPDATE raw.property_day SET contribution_after_supplied_costs_usd=contribution_after_supplied_costs_usd+tech_labor_cost_usd')
    build_descriptive(con)
    checks = {c['check']: c for c in validate_descriptive(con)}
    assert not checks['mart_floor_daily.source_accounting']['passed']


def test_all_five_marts_are_published_and_stage_three_failure_preserves_database(tmp_path,monkeypatch):
    dataset = tmp_path/'source'
    (dataset/'data').mkdir(parents=True)
    (dataset/'data'/'manifest.json').write_text(json.dumps({'version':'0.9.0-draft','files':[]}))

    def register(con,dataset):
        create_descriptive_sources(con)
        return []

    monkeypatch.setattr(build,'register_sources',register)
    monkeypatch.setattr(build,'validate_sources',lambda *args: {'passed':True,'checks':[],'hashes_verified':False,'scope':'Synthetic inputs.'})
    monkeypatch.setattr('casino_pipeline.machine_daily.ANALYSIS_START','2025-03-08')
    monkeypatch.setattr('casino_pipeline.machine_daily.ANALYSIS_END','2025-03-09')
    output = tmp_path/'output'
    assert build.run(dataset,output,stage=3)['passed']
    path = output/'casino.duckdb'
    before = path.read_bytes()
    with duckdb.connect(str(path),read_only=True) as con:
        assert con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name='marts'").fetchone()[0] == 5
        assert con.execute("SELECT json_extract_string(document,'$.stage') FROM metadata.build_manifest").fetchone()[0] == '3_descriptive'
        assert con.execute("SELECT count(*) FROM metadata.mart_columns WHERE table_name='marts.mart_zone_daily'").fetchone()[0]>0
        assert con.execute("SELECT count(*) FROM duckdb_views() WHERE schema_name IN ('raw','staging')").fetchone()[0]==0

    def bad_register(con,dataset):
        register(con,dataset)
        con.execute('INSERT INTO raw.city_visitation_monthly SELECT * FROM raw.city_visitation_monthly LIMIT 1')
        return []

    monkeypatch.setattr(build,'register_sources',bad_register)
    assert not build.run(dataset,output,stage=3)['passed']
    assert path.read_bytes()==before
