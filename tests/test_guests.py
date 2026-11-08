"""Known-answer stage-four fixtures, independent of the full release."""

from decimal import Decimal

import duckdb
import pytest

from casino_pipeline.database import build_connection
from casino_pipeline.guests import build_guests, validate_guests, validate_guest_inputs, CONTRACTS
from casino_pipeline.descriptive import finalize_contract
from casino_pipeline.analysis.players import build_player_diagnostics


def create_guest_sources(con):
    con.execute("""
    CREATE TABLE staging.analysis_window AS SELECT DATE '2025-01-01' AS start_date,DATE '2025-02-28' AS end_date;
    CREATE TABLE raw.calendar_day AS SELECT d::DATE AS gaming_date,d+INTERVAL '14 hours' AS gaming_day_start_utc,
      d+INTERVAL '38 hours' AS gaming_day_end_utc FROM generate_series(
        TIMESTAMP '2025-01-01',TIMESTAMP '2025-02-28',INTERVAL '1 day') days(d);
    CREATE TABLE raw.players (player_id VARCHAR,home_region VARCHAR,age_band VARCHAR,opening_tier VARCHAR,
      enrolled_at_utc TIMESTAMP,opening_lifetime_points BIGINT);
    INSERT INTO raw.players VALUES
      ('P1','West','Adult','Bronze','2020-01-01',999999),
      ('P2','East',NULL,'Silver','2020-01-01',50000),
      ('P3',NULL,'Older','Bronze','2025-02-10 14:00:00',0),
      ('P4','West','Adult','Gold','2020-01-01',1000000),
      ('P5','West','Adult','Gold','2020-01-01',2000000),
      ('P6','West','Adult','Silver','2025-03-05',0);
    CREATE TABLE raw.trips (observed_visit_id VARCHAR,player_id VARCHAR,first_observed_at_utc TIMESTAMP,observation_complete BOOLEAN);
    INSERT INTO raw.trips VALUES ('V1','P1','2025-01-31 22:00:00',true),
      ('V2','P1','2025-02-02 20:00:00',false),('V3','P2','2025-01-15 20:00:00',true),
      ('V4','P3','2025-02-11 20:00:00',true);
    CREATE TABLE raw.sessions (session_segment_id VARCHAR,logical_session_id VARCHAR,player_id VARCHAR,
      observed_visit_id VARCHAR,gaming_date DATE,start_utc TIMESTAMP,end_utc TIMESTAMP,
      coin_in_cents BIGINT,payout_cents BIGINT,theo_cents DECIMAL(24,8));
    INSERT INTO raw.sessions VALUES
      ('S1','LS1','P1','V1','2025-01-31','2025-01-31 22:00:00','2025-01-31 23:00:00',10000,8000,1000),
      ('S2','LS2','P1','V1','2025-02-01','2025-02-01 20:00:00','2025-02-01 21:00:00',20000,19000,2000),
      ('S3','LS3','P1','V2','2025-02-02','2025-02-02 20:00:00','2025-02-02 21:00:00',5000,10000,500),
      ('S4','LS4','P2','V3','2025-01-15','2025-01-15 20:00:00','2025-01-15 21:00:00',5000,7000,500);
    CREATE TABLE raw.fnb_transactions (transaction_id VARCHAR,player_id VARCHAR,observed_visit_id VARCHAR,
      event_at_utc TIMESTAMP,cash_receipt_cents BIGINT,cogs_cents BIGINT,face_value_cents BIGINT,comp_id VARCHAR);
    INSERT INTO raw.fnb_transactions VALUES
      ('F1','P1','V1','2025-01-31 23:00:00',1000,400,1000,NULL),
      ('F2','P1','V1','2025-02-01 13:00:00',500,200,500,NULL),
      ('F3','P1','V1','2025-02-01 21:00:00',2000,800,2000,NULL),
      ('F4','P1','V2','2025-02-02 21:00:00',0,300,1500,'R1'),
      ('F5','P3','V4','2025-02-11 20:00:00',0,200,1000,'R2'),
      ('F6',NULL,NULL,'2025-01-31 23:00:00',9000,4500,9000,NULL),
      ('F7','P1',NULL,'2025-02-12 20:00:00',700,200,700,NULL);
    CREATE TABLE raw.loyalty_ledger (loyalty_event_id VARCHAR,player_id VARCHAR,event_type VARCHAR,
      event_at_utc TIMESTAMP,points_delta BIGINT,face_value_cents BIGINT,economic_cost_cents BIGINT,
      redeemed_pos_id VARCHAR,tier_before VARCHAR,tier_after VARCHAR);
    INSERT INTO raw.loyalty_ledger VALUES
      ('A1','P1','award','2025-01-31 23:00:00',1000,0,0,NULL,'Bronze','Bronze'),
      ('A2','P1','award','2025-02-01 21:00:00',2000,0,0,NULL,'Bronze','Gold'),
      ('A3','P3','award','2025-02-10 16:00:00',500,0,0,NULL,'Bronze','Bronze'),
      ('A4','P4','award','2025-01-01 20:00:00',5000,0,0,NULL,'Gold','Gold'),
      ('A5','P4','award','2025-03-01 14:00:00',300,0,0,NULL,'Gold','Gold'),
      ('R1','P1','redeem','2025-02-02 21:00:00',-100,1500,300,'F4','Gold','Gold'),
      ('R2','P3','redeem','2025-02-11 20:00:00',-50,1000,200,'F5','Bronze','Bronze');
    CREATE TABLE raw.player_period (player_id VARCHAR,period_month VARCHAR,home_region VARCHAR,age_band VARCHAR,
      opening_tier VARCHAR,tier_end VARCHAR,observed_visits BIGINT,incomplete_visits BIGINT,sessions BIGINT,
      carded_play_hours DOUBLE,tracked_coin_in_usd DECIMAL(18,2),tracked_payout_usd DECIMAL(18,2),
      tracked_net_usd DECIMAL(18,2),theo_usd DECIMAL(18,4),luck_residual_usd DECIMAL(18,4),
      linked_pos_cash_usd DECIMAL(18,2),linked_pos_cogs_usd DECIMAL(18,2),comps_redeemed BIGINT,
      comp_face_value_usd DECIMAL(18,2),comp_cost_usd DECIMAL(18,2),points_earned BIGINT,
      points_redeemed BIGINT,tracked_contribution_usd DECIMAL(18,2));
    INSERT INTO raw.player_period VALUES
      ('P1','2025-01','West','Adult','Bronze','Bronze',1,0,1,1,100,80,-20,10,-10,15,6,0,0,0,1000,0,29),
      ('P1','2025-02','West','Adult','Bronze','Gold',2,1,2,2,250,290,40,25,65,27,13,1,15,3,2000,100,-26),
      ('P2','2025-01','East',NULL,'Silver','Silver',1,0,1,1,50,70,20,5,25,0,0,0,0,0,0,0,-20),
      ('P3','2025-02',NULL,'Older','Bronze','Bronze',1,0,0,0,0,0,0,0,0,0,2,1,10,2,500,50,-2),
      ('P4','2025-01','West','Adult','Gold','Gold',0,0,0,0,0,0,0,0,0,0,0,0,0,0,5000,0,0);
    CREATE TABLE raw.machine_day AS SELECT gaming_date,sum(coin_in_cents)::BIGINT AS carded_coin_in_cents,
      sum(payout_cents)::BIGINT AS carded_payout_cents FROM raw.sessions GROUP BY gaming_date;
    CREATE TABLE marts.mart_floor_daily AS SELECT c.gaming_date,
      coalesce(sum(l.economic_cost_cents*0.01) FILTER(WHERE event_type='redeem'),0)::DECIMAL(24,2) AS comp_cost_usd
      FROM raw.calendar_day c LEFT JOIN raw.loyalty_ledger l
      ON cast(l.event_at_utc-INTERVAL '14 hours' AS DATE)=c.gaming_date GROUP BY c.gaming_date;
    """)


@pytest.fixture
def guest_connection(connection):
    create_guest_sources(connection)
    return connection


def test_known_answers_source_reconciliation_and_preserved_player_rows(guest_connection):
    con = guest_connection
    assert all(c['passed'] for c in validate_guest_inputs(con))
    build_guests(con)
    assert not [c for c in validate_guests(con) if not c['passed']]
    assert con.execute('SELECT count(*) FROM marts.mart_player_month').fetchone()[0]==5
    player = con.execute("""SELECT tracked_coin_in_usd,tracked_net_usd,actual_tracked_loss_usd,
      tracked_contribution_usd,opening_tier,tier_end,winner_flag,above_expected_loss_flag,protective_status
      FROM marts.mart_player_month WHERE player_id='P1' AND month_start='2025-02-01'""").fetchone()
    assert player==(Decimal('250'),Decimal('40'),Decimal('-40'),Decimal('-26'),'Bronze','Gold',True,None,'not_configured')
    assert con.execute("SELECT age_band FROM marts.mart_player_month WHERE player_id='P2'").fetchone()[0]=='Unknown'
    assert con.execute('SELECT sum(tracked_contribution_usd) FROM marts.mart_player_month').fetchone()[0]==Decimal('-19')


def test_cross_month_visits_and_incomplete_or_non_gaming_winner_denominators(guest_connection):
    con = guest_connection
    build_guests(con)
    visit = con.execute("""SELECT observed_visits,visit_assigned_coin_in_usd,visit_assigned_payout_usd,
      visit_assigned_pos_cash_usd,complete_gaming_visits,winning_visits,winner_share_complete_visits
      FROM marts.mart_visits_month WHERE month_start='2025-01-01' AND opening_tier='Bronze'""").fetchone()
    assert visit==(1,Decimal('300'),Decimal('270'),Decimal('35'),1,0,0.0)
    assert con.execute("""SELECT count(*) FROM marts.mart_visits_month WHERE month_start='2025-02-01'
      AND winner_share_complete_visits IS NULL""").fetchone()[0]==2
    assert con.execute("""SELECT visit_assigned_pos_cash_usd FROM marts.mart_visits_month
      WHERE month_start='2025-02-01' AND home_region='West'""").fetchone()[0]==0


def test_points_balance_inactive_cohort_new_enrollment_and_fixed_tiers(guest_connection):
    con = guest_connection
    build_guests(con)
    assert con.execute('SELECT count(*) FROM marts.mart_comps_tier_month').fetchone()[0]==6
    bronze = con.execute("""SELECT cohort_players,active_players,points_balance_start,points_earned,
      points_redeemed,points_balance_end FROM marts.mart_comps_tier_month
      WHERE opening_tier='Bronze' ORDER BY month_start""").fetchall()
    assert bronze==[(1,1,0,1000,0,1000),(2,2,1000,2500,150,3350)]
    assert con.execute("""SELECT cohort_players,active_players,points_balance_start,points_balance_end
      FROM marts.mart_comps_tier_month WHERE opening_tier='Gold' AND month_start='2025-02-01'""").fetchone()==(2,0,5000,5000)
    assert con.execute("""SELECT cohort_players FROM marts.mart_comps_tier_month
      WHERE opening_tier='Silver' ORDER BY month_start""").fetchall()==[(1,),(1,)]
    assert con.execute("SELECT points_balance_end FROM marts.mart_comps_daily ORDER BY gaming_date DESC LIMIT 1").fetchone()[0]==8350
    assert con.execute("SELECT records FROM diagnostics.guest_coverage WHERE metric='ledger_outside_analysis_window'").fetchone()[0]==1


def test_gaming_dates_uncarded_sales_costs_once_and_nonpositive_denominators(guest_connection):
    con = guest_connection
    build_guests(con)
    assert con.execute('SELECT count(*) FROM marts.mart_comps_daily').fetchone()[0]==59
    assert con.execute("""SELECT linked_pos_cash_usd,linked_pos_cogs_usd FROM marts.mart_comps_daily
      WHERE gaming_date='2025-01-31'""").fetchone()==(Decimal('15'),Decimal('6'))
    assert con.execute("""SELECT actual_tracked_loss_usd,comp_cost_usd,tracked_contribution_usd,
      comp_cost_per_actual_loss,actual_loss_ratio_status,policy_change_candidate,change_status
      FROM marts.mart_comps_daily WHERE gaming_date='2025-02-02'""").fetchone()==(
        Decimal('-50'),Decimal('3'),Decimal('-53'),None,'negative_denominator',None,'not_configured')
    assert con.execute("""SELECT comp_cost_per_actual_loss,actual_loss_ratio_status,
      total_spend_ratio_status FROM marts.mart_comps_daily WHERE gaming_date='2025-02-11'""").fetchone()==(None,'zero_denominator','zero_denominator')
    assert con.execute("SELECT records,amount_usd FROM diagnostics.guest_coverage WHERE metric='carded_pos_without_visit'").fetchone()==(1,Decimal('7'))


def test_period_outcomes_aggregate_players_before_winner_and_concentration_calculations(guest_connection):
    con = guest_connection
    build_guests(con)
    assert con.execute("""SELECT tracked_players,players_with_gaming,winning_players,winner_share_gaming_players,
      gross_player_loss_usd,gross_player_win_usd,net_player_loss_usd,top_1pct_gross_loss_share
      FROM diagnostics.player_outcomes""").fetchone()==(4,2,2,1.0,Decimal('0'),Decimal('40'),Decimal('-40'),None)
    con.execute("UPDATE marts.mart_player_month SET actual_tracked_loss_usd=30 WHERE player_id='P2'")
    con.execute('DROP TABLE diagnostics.player_outcomes')
    build_player_diagnostics(con)
    assert con.execute('SELECT top_1pct_gross_loss_share,top_10pct_gross_loss_share FROM diagnostics.player_outcomes').fetchone()==(1.0,1.0)


@pytest.mark.parametrize('mutation,expected', [
    ("UPDATE raw.sessions SET player_id='missing' WHERE session_segment_id='S1'",'guests.sessions.players'),
    ("UPDATE raw.fnb_transactions SET player_id='P2' WHERE transaction_id='F1'",'guests.fnb_transactions.visit_identity'),
    ("UPDATE raw.loyalty_ledger SET economic_cost_cents=400 WHERE loyalty_event_id='R1'",'guests.ledger.redemption_links'),
    ("UPDATE raw.loyalty_ledger SET redeemed_pos_id=NULL WHERE loyalty_event_id='R1'",'guests.ledger.redemption_links'),
    ("UPDATE raw.loyalty_ledger SET points_delta=100 WHERE loyalty_event_id='R1'",'guests.ledger.events'),
    ("UPDATE staging.analysis_window SET start_date='2025-01-02'",'guests.whole_month_single_year_window'),
])
def test_invalid_links_values_and_windows_fail(guest_connection,mutation,expected):
    con = guest_connection
    con.execute(mutation)
    checks = {c['check']:c for c in validate_guest_inputs(con)}
    assert not checks[expected]['passed']


@pytest.mark.parametrize('mutation,expected', [
    ("UPDATE raw.player_period SET points_earned=1 WHERE player_id='P1' AND period_month='2025-01'",'mart_player_month.independent_fact_reconciliation'),
    ("UPDATE raw.player_period SET tracked_contribution_usd=-29 WHERE player_id='P1' AND period_month='2025-02'",'mart_player_month.accounting'),
    ("UPDATE raw.machine_day SET carded_coin_in_cents=0 WHERE gaming_date='2025-01-31'",'mart_comps_daily.carded_meter_reconciliation'),
    ("UPDATE raw.loyalty_ledger SET points_delta=-600 WHERE loyalty_event_id='R2'",'guests.individual_points_balance'),
])
def test_independent_accounting_reconciliations_detect_corruption(guest_connection,mutation,expected):
    con = guest_connection
    con.execute(mutation)
    build_guests(con)
    checks = {c['check']:c for c in validate_guests(con)}
    assert not checks[expected]['passed']


def test_subwindow_points_start_from_annual_history(guest_connection):
    con = guest_connection
    con.execute("UPDATE staging.analysis_window SET start_date='2025-02-01'")
    build_guests(con)
    assert not [c for c in validate_guests(con) if not c['passed']]
    assert con.execute("SELECT points_balance_start FROM marts.mart_comps_daily ORDER BY gaming_date LIMIT 1").fetchone()[0]==6000


def test_gaming_date_conversion_respects_dst_and_repeated_local_hour(guest_connection):
    con = guest_connection
    build_guests(con)
    assert con.execute("""SELECT staging.gaming_date(TIMESTAMP '2025-03-09 12:59:59')::VARCHAR,
      staging.gaming_date(TIMESTAMP '2025-03-09 13:00:00')::VARCHAR,
      staging.gaming_date(TIMESTAMP '2025-11-02 08:30:00')::VARCHAR,
      staging.gaming_date(TIMESTAMP '2025-11-02 09:30:00')::VARCHAR""").fetchone()==(
        '2025-03-08','2025-03-09','2025-11-01','2025-11-01')


def test_guest_marts_enforce_keys_and_work_without_source_views(tmp_path):
    path = tmp_path/'guests.duckdb'
    with build_connection(path) as con:
        create_guest_sources(con)
        build_guests(con)
        assert all(c['passed'] for c in validate_guests(con))
        for contract in CONTRACTS:
            finalize_contract(con,contract)
        con.execute('DROP SCHEMA raw CASCADE')
        con.execute('DROP SCHEMA staging CASCADE')
    with duckdb.connect(str(path),read_only=True) as con:
        assert con.execute('SELECT count(*) FROM marts.mart_player_month').fetchone()[0]==5
        assert con.execute('SELECT sum(comp_cost_usd) FROM marts.mart_comps_daily').fetchone()[0]==Decimal('5')
