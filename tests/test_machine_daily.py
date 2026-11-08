"""Known-answer accounting, DST, partial-day, placement and publication tests."""

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from casino_pipeline import build
from casino_pipeline.database import build_connection
from casino_pipeline.machine_daily import build_machine_daily, validate_machine_daily


def create_machine_sources(con):
    con.execute("""
    CREATE TABLE raw.machine_day (
      machine_id VARCHAR, gaming_date DATE, location_id VARCHAR, config_id VARCHAR, active BOOLEAN,
      meter_status VARCHAR, scheduled_seconds BIGINT, available_seconds BIGINT, occupied_seconds BIGINT,
      paid_spins BIGINT, carded_spins BIGINT, coin_in_cents BIGINT, payout_cents BIGINT,
      house_win_cents BIGINT, carded_coin_in_cents BIGINT, carded_payout_cents BIGINT,
      theo_cents DECIMAL(24,8), carded_theo_cents DECIMAL(24,8), sum_bet_squared DOUBLE);
    INSERT INTO raw.machine_day VALUES
      ('M1','2025-03-08','L1','C1',true,'reported',82800,82800,3600,100,50,10000,9000,1000,5000,4500,1000,500,1000000),
      ('M1','2025-03-09','L2','C2',true,'reported',86400,0,0,0,0,0,0,0,0,0,0,0,0),
      ('M2','2025-03-08','L2','C1',true,'reported',7200,3600,1800,100,50,10000,12000,-2000,5000,6000,1000,500,1000000),
      ('M3','2025-03-08',NULL,NULL,false,'not_installed',0,0,0,0,0,0,0,0,0,0,0,0,0);
    CREATE TABLE raw.calendar_day (
      gaming_date DATE, scheduled_seconds BIGINT, gaming_day_start_utc TIMESTAMP, gaming_day_end_utc TIMESTAMP);
    INSERT INTO raw.calendar_day VALUES
      ('2025-03-08',82800,'2025-03-08 14:00:00','2025-03-09 13:00:00'),
      ('2025-03-09',86400,'2025-03-09 13:00:00','2025-03-10 13:00:00');
    CREATE TABLE raw.machines (machine_id VARCHAR, manufacturer VARCHAR, lease_class VARCHAR);
    INSERT INTO raw.machines VALUES ('M1','Maker','owned'),('M2','Maker','owned');
    CREATE TABLE raw.game_math (config_id VARCHAR, theme VARCHAR, configured_rtp DECIMAL(10,8),
      volatility_class VARCHAR, payout_multiplier_variance DECIMAL(18,8));
    INSERT INTO raw.game_math VALUES ('C1','Game one',0.9,'low',4),('C2','Game two',0.95,'high',9);
    CREATE TABLE raw.floor_locations (location_id VARCHAR, zone_id VARCHAR, bank_id VARCHAR,
      x_m DOUBLE, y_m DOUBLE, node_type VARCHAR);
    INSERT INTO raw.floor_locations VALUES ('L1','Z1','B1',1,2,'slot'),('L2','Z2','B2',NULL,NULL,'slot');
    CREATE TABLE raw.placements (placement_id VARCHAR, machine_id VARCHAR, location_id VARCHAR,
      config_id VARCHAR, effective_from_utc TIMESTAMP, effective_to_utc TIMESTAMP);
    INSERT INTO raw.placements VALUES
      ('P1','M1','L1','C1','2025-03-08 14:00:00','2025-03-09 13:00:00'),
      ('P2','M1','L2','C2','2025-03-09 13:00:00',NULL),
      ('P3','M2','L2','C1','2025-03-09 11:00:00',NULL);
    CREATE TABLE raw.prepared_daily_view AS SELECT machine_id, gaming_date, location_id, config_id,
      active, 'Zone'::VARCHAR AS zone_name,
      (coin_in_cents*0.01)::DECIMAL(18,2) AS coin_in_usd,
      (payout_cents*0.01)::DECIMAL(18,2) AS payout_usd,
      (house_win_cents*0.01)::DECIMAL(18,2) AS house_win_usd,
      (theo_cents*0.01)::DECIMAL(18,4) AS theo_usd,
      available_seconds/3600.0 AS available_hours, occupied_seconds/3600.0 AS occupied_hours,
      1.00::DECIMAL(18,2) AS lease_cost_usd, 2.00::DECIMAL(18,2) AS service_cost_usd,
      3.00::DECIMAL(18,2) AS power_cost_usd, 4.00::DECIMAL(18,2) AS repair_cost_usd,
      0::BIGINT AS faults_opened,
      (house_win_cents*0.01-10)::DECIMAL(18,2) AS contribution_after_supplied_costs_usd
      FROM raw.machine_day WHERE active;
    """)


def test_known_answer_accounting_dst_partial_days_moves_and_nulls(connection):
    create_machine_sources(connection)
    build_machine_daily(connection)
    assert all(c["passed"] for c in validate_machine_daily(connection))
    assert connection.execute("SELECT count(*) FROM marts.mart_machine_daily").fetchone()[0] == 3
    row = connection.execute("""SELECT scheduled_seconds, calendar_day_seconds, availability_ratio,
      house_win_usd, machine_cost_usd, actual_contribution_usd, outcome_variance_usd2
      FROM marts.mart_machine_daily WHERE machine_id='M2'""").fetchone()
    assert row == (7200, 82800, 0.5, Decimal('-20.00'), Decimal('10.00'), Decimal('-30.00'), 400.0)
    zero = connection.execute("""SELECT location_id, config_id, theme, observed_hold, theo_per_available_hour,
      availability_ratio FROM marts.mart_machine_daily WHERE gaming_date='2025-03-09'""").fetchone()
    assert zero == ('L2', 'C2', 'Game two', None, None, 0.0)


@pytest.mark.parametrize('mutation,expected', [
    ("DELETE FROM raw.floor_locations WHERE location_id='L1'", 'required_values'),
    ("INSERT INTO raw.prepared_daily_view SELECT * FROM raw.prepared_daily_view LIMIT 1", 'key'),
    ("UPDATE raw.placements SET effective_to_utc=NULL WHERE placement_id='P1'", 'placement_intervals'),
    ("UPDATE raw.machine_day SET available_seconds=90000 WHERE machine_id='M2'", 'duration_bounds'),
    ("UPDATE raw.prepared_daily_view SET coin_in_usd=999 WHERE machine_id='M2'", 'prepared_reconciliation'),
])
def test_bad_inputs_are_not_silently_dropped(connection, mutation, expected):
    create_machine_sources(connection)
    connection.execute(mutation)
    build_machine_daily(connection)
    checks = {c['check'].split('.')[-1]: c for c in validate_machine_daily(connection)}
    assert not checks[expected]['passed']


def test_publication_is_standalone_and_failed_rebuild_preserves_previous(tmp_path, monkeypatch):
    dataset = tmp_path / 'source'
    (dataset / 'data').mkdir(parents=True)
    (dataset / 'data' / 'manifest.json').write_text(json.dumps({'version': '0.9.0-draft', 'files': []}))

    def register(con, dataset):
        create_machine_sources(con)
        return []

    monkeypatch.setattr(build, 'register_sources', register)
    monkeypatch.setattr(build, 'validate_sources', lambda *args: {
        'passed': True, 'checks': [], 'hashes_verified': False, 'scope': 'Synthetic inputs.'})
    output = tmp_path / 'output'
    assert build.run(dataset, output, stage=2)['passed']
    path = output / 'casino.duckdb'
    before = path.read_bytes()
    # Read-only connection has no raw/staging views or filesystem dependencies.
    with duckdb.connect(str(path), read_only=True) as con:
        assert con.execute('SELECT count(*) FROM marts.mart_machine_daily').fetchone()[0] == 3
        assert con.execute("SELECT count(*) FROM duckdb_views() WHERE schema_name IN ('raw','staging')").fetchone()[0] == 0
        assert con.execute("SELECT json_extract_string(document,'$.stage') FROM metadata.build_manifest").fetchone()[0] == '2_machine_daily'

    def bad_register(con, dataset):
        register(con, dataset)
        con.execute("DELETE FROM raw.floor_locations WHERE location_id='L1'")
        return []

    monkeypatch.setattr(build, 'register_sources', bad_register)
    assert not build.run(dataset, output, stage=2)['passed']
    assert path.read_bytes() == before
    assert not list(output.glob('.casino-build-*'))

    monkeypatch.setattr(build, 'register_sources', register)
    original_replace = Path.replace

    def locked_replace(self, target):
        if self.suffix == '.duckdb':
            raise PermissionError('Simulated app reader lock')
        return original_replace(self, target)

    monkeypatch.setattr(Path, 'replace', locked_replace)
    failed = build.run(dataset, output, stage=2)
    assert not failed['passed']
    assert failed['checks'][-1]['check'] == 'database.publication'
    assert path.read_bytes() == before
