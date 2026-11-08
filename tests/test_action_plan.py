"""Checked-in portfolio pricing and net-scenario accounting."""

import csv
from decimal import Decimal
import gzip
from pathlib import Path
from datetime import date,timedelta

import pandas as pd

from casino_pipeline.actions import prepare_proposal, validate_portfolio
from dashboard.action_plan import net_scenarios


def test_scenario_bounds_subtract_proposal_cost_once_and_skip_unpriced_effects():
    actions=pd.DataFrame([
        dict(net_benefit_usd=60,total_cost_usd=40,benefit_low_usd=50,benefit_high_usd=150),
        dict(net_benefit_usd=None,total_cost_usd=1200,benefit_low_usd=None,benefit_high_usd=None),
    ])
    result=net_scenarios(actions)
    assert len(result)==1
    assert result.iloc[0].net_low==10
    assert result.iloc[0].net_high==110
    assert result.iloc[0].net_benefit_usd==60


def test_checked_in_portfolio_allocates_full_budget_without_type_cap():
    root=Path(__file__).resolve().parents[1]
    with gzip.open(root/'dashboard-royale-main/data/2_machine_decision/action_catalog.csv.gz','rt',encoding='utf-8') as f:
        catalogue={row['action_type_id']:row for row in csv.DictReader(f)}
    for action in catalogue.values():
        for field in ['unit_cost_cents','recurring_cost_cents_per_day','lead_days','downtime_minutes','quantity_limit']:
            action[field]=int(action[field])
    with (root/'config/action_proposals.csv').open(newline='',encoding='utf-8') as f:
        configured=list(csv.DictReader(f))
    assert len(configured)==27
    prepared=[]
    target_sets={}
    for row in configured:
        targets={row['target_id']} if row['target_type']=='machine' else {'M-1265','M-1050','M-1158'}
        forecast={date(2025,7,1)+timedelta(days=i):Decimal('1000000') for i in range(30)}
        prepared.append(prepare_proposal(row,catalogue[row['action_type_id']],targets,forecast))
        target_sets[row['proposal_line_id']]=targets
    validate_portfolio(prepared,catalogue,target_sets)
    assert sum(row['total_cost_usd'] for row in prepared)==Decimal('100000.00')
    assert len({row['action_type_id'] for row in prepared})==6
    leases=[row for row in prepared if row['action_type_id']=='A-REPLACE-LEASE']
    assert len({row['target_id'] for row in leases})==10
    assert all(row['total_cost_usd']==Decimal('3380') for row in leases)
    assert all(row['benefit_days_per_unit']==15.75 for row in leases)
    assert all(row['net_benefit_usd'] is None for row in prepared if row['action_type_id'] in {'A-INSPECT','A-SURVEY'})
