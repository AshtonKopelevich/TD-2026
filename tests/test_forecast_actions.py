"""Three focused stage-seven checks; no earlier pipeline rebuilds."""

from datetime import date
from decimal import Decimal

import pytest

from casino_pipeline.database import build_connection
from casino_pipeline.model.forecast import build_forecast,validate_forecast
from casino_pipeline.actions import prepare_proposal,validate_portfolio,build_actions,validate_actions


def forecast_sources(con,changed_holdout=False):
    con.execute('''CREATE TABLE marts.mart_floor_daily AS SELECT d::DATE AS gaming_date,
      (1000+100*(isodow(d)-1))::DECIMAL(24,2) AS coin_in_usd
      FROM generate_series(TIMESTAMP '2025-01-01',TIMESTAMP '2025-06-30',INTERVAL '1 day') t(d);
      CREATE TABLE raw.calendar_day AS SELECT gaming_date,NULL::VARCHAR AS federal_holiday FROM marts.mart_floor_daily;
      CREATE TABLE raw.events (start_date DATE,end_date DATE,announced_date DATE,local_scope VARCHAR);
      INSERT INTO raw.events VALUES ('2025-06-09','2025-06-15','2025-05-26','property');''')
    if changed_holdout:
        con.execute("UPDATE marts.mart_floor_daily SET coin_in_usd=coin_in_usd+5000 WHERE gaming_date>='2025-05-01'")


def test_forecast_splits_candidate_selection_and_holdout_isolation():
    saved = None
    for changed in (False,True):
        with build_connection() as con:
            forecast_sources(con,changed)
            build_forecast(con)
            assert all(check['passed'] for check in validate_forecast(con))
            assert con.execute('SELECT count(*) FROM marts.mart_forecast').fetchone()[0]==211
            predictions = con.execute("SELECT forecast_date,model_prediction_usd FROM marts.mart_forecast WHERE split='test' ORDER BY forecast_date").fetchall()
            if saved is None:
                saved = predictions
            else:
                assert predictions==saved  # May-Jun target changes must not change May-Jun forecasts.
            assert con.execute("SELECT selected_method FROM diagnostics.forecast_selection").fetchone()[0]=='weekday_mean'
            assert con.execute("SELECT property_event FROM diagnostics.forecast_features WHERE split='test' AND forecast_date='2025-06-10'").fetchone()[0] is False
            assert con.execute("SELECT actual_coin_in_usd,fit_end FROM marts.mart_forecast WHERE forecast_date='2025-07-01'").fetchone()==(None,date(2025,6,30))


def catalog():
    return {
      'A-REPLACE-LEASE':dict(action_type_id='A-REPLACE-LEASE',name='Lease',unit='machine',unit_cost_cents=250000,
        recurring_cost_cents_per_day=5500,lead_days=14,downtime_minutes=360,quantity_limit=20,incompatibility_group='same_machine',notes=''),
      'A-MOVE-BANK':dict(action_type_id='A-MOVE-BANK',name='Bank move',unit='bank',unit_cost_cents=950000,
        recurring_cost_cents_per_day=0,lead_days=5,downtime_minutes=480,quantity_limit=3,incompatibility_group='same_machine',notes=''),
    }


def proposal(line,action,target_type,target):
    return dict(proposal_line_id=line,action_type_id=action,target_type=target_type,target_id=target,selected='true',quantity='1',
      effect_assumption='Per-unit daily uplift before proposal charges',cost_assumption='New lease charged in proposal only',
      evidence_refs='marts.mart_machine_scorecard',measurement_metric='Expected contribution',control_definition='Matched machines',
      limitation='Scenario, not causal effect',expected_uplift_usd_per_day='100',low_uplift_usd_per_day='50',high_uplift_usd_per_day='150',
      downtime_opportunity_cost_usd_per_hour='10')


def test_lease_price_benefit_downtime_and_expanded_bank_conflicts():
    cat = catalog()
    lease = prepare_proposal(proposal('P1','A-REPLACE-LEASE','machine','M1'),cat['A-REPLACE-LEASE'],{'M1'},{})
    assert lease['total_cost_usd']==Decimal('3380.00')
    assert lease['action_downtime_hours']==6
    assert lease['benefit_days_per_unit']==15.75
    assert lease['benefit_before_action_cost_usd']==Decimal('1515.00')
    assert lease['net_benefit_usd']==Decimal('-1865.00')
    assert lease['half_effect_net_benefit_usd']==Decimal('-2622.50')
    bank = prepare_proposal(proposal('P2','A-MOVE-BANK','bank','B1'),cat['A-MOVE-BANK'],{'M1','M2'},{})
    assert bank['action_downtime_hours']==16
    with pytest.raises(ValueError,match='conflict'):
        validate_portfolio([lease,bank],cat,{'P1':{'M1'},'P2':{'M1','M2'}})
    with pytest.raises(ValueError,match='budget'):
        validate_portfolio([{**lease,'total_cost_usd':Decimal('100001')}],cat,{'P1':{'M1'}})


def test_empty_proposals_publish_a_typed_mart_and_unallocated_budget(connection,tmp_path):
    con = connection
    con.execute('''CREATE TABLE raw.action_catalog (action_type_id VARCHAR,name VARCHAR,unit VARCHAR,unit_cost_cents BIGINT,
      recurring_cost_cents_per_day BIGINT,lead_days INTEGER,downtime_minutes INTEGER,quantity_limit INTEGER,incompatibility_group VARCHAR,notes VARCHAR)''')
    con.executemany('INSERT INTO raw.action_catalog VALUES (?,?,?,?,?,?,?,?,?,?)',[tuple(r.values()) for r in catalog().values()])
    con.execute('''CREATE TABLE raw.placements AS SELECT 'M1' AS machine_id,'L1' AS location_id,
      TIMESTAMP '2020-01-01' AS effective_from_utc,NULL::TIMESTAMP AS effective_to_utc;
      CREATE TABLE raw.floor_locations AS SELECT 'L1' AS location_id,'B1' AS bank_id,'Z1' AS zone_id,'slot' AS node_type;
      CREATE TABLE raw.machines AS SELECT 'M1' AS machine_id,'Maker' AS manufacturer;
      CREATE TABLE raw.shift_roster AS SELECT 'day' AS shift;
      CREATE TABLE marts.mart_forecast AS SELECT DATE '2025-07-01' AS forecast_date,1000::DECIMAL(24,2) AS model_prediction_usd,'future' AS split;''')
    path = tmp_path/'proposals.csv'
    path.write_text('proposal_line_id,action_type_id,target_type,target_id,selected,quantity,effect_assumption,evidence_refs\n')
    build_actions(con,path)
    assert all(check['passed'] for check in validate_actions(con))
    assert con.execute('SELECT count(*) FROM marts.mart_actions').fetchone()[0]==0
    assert con.execute('SELECT status,spent_usd,unallocated_usd FROM diagnostics.action_portfolio').fetchone()==(
      'no_proposals',Decimal('0.00'),Decimal('100000.00'))
