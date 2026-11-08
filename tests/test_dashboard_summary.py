"""Known-answer observed earnings comparisons and useful bank filtering."""

from datetime import date

import duckdb
import pandas as pd
import pytest

from dashboard import machine_summary as summary
from dashboard.data import Filters


def test_bank_filter_keeps_all_bank_machines_and_outside_bank_peer_context(monkeypatch):
    con=duckdb.connect()
    con.execute('CREATE SCHEMA marts')
    con.execute('''CREATE TABLE marts.mart_machine_daily (
        machine_id VARCHAR,gaming_date DATE,month_start DATE,zone_id VARCHAR,zone_name VARCHAR,
        bank_id VARCHAR,available_seconds BIGINT,scheduled_seconds BIGINT,
        house_win_usd DOUBLE,actual_contribution_usd DOUBLE,coin_in_usd DOUBLE,machine_cost_usd DOUBLE)''')
    # Target earns $10/hr; three other-bank peers earn $20/hr. A retired
    # low earner must not displace the current bank's target in this window.
    for day in (1,2):
        for machine,bank,income in [('M1','B1',10),('P1','B2',20),('P2','B2',20),('P3','B3',20)]:
            con.execute('INSERT INTO marts.mart_machine_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                [machine,date(2025,1,day),date(2025,1,1),'Z1','Zone one',bank,3600,3600,income,income-2,100,2])
    con.execute("INSERT INTO marts.mart_machine_daily VALUES ('old','2025-01-01','2025-01-01','Z1','Zone one','B1',0,3600,0,-2,0,2)")
    monkeypatch.setattr(summary,'query',lambda sql,params:con.execute(sql,params).df())
    data=summary.observations(Filters(start=date(2025,1,1),end=date(2025,1,2),zone='Z1',bank='B1'))
    assert set(data.machine_id)=={'M1'}
    assert data.peer_income_rate.tolist()==[20,20]
    machines,_=summary.summarize(data)
    row=machines.iloc[0]
    assert row.income_rate==10
    assert row.contribution_rate==8
    assert row.income_gap==-10
    con.close()


def test_ratios_use_hours_and_missing_peer_days_are_excluded_from_comparison():
    data=pd.DataFrame([
        dict(machine_id='M1',gaming_date=date(2025,1,1),month_start=pd.Timestamp('2025-01-01'),
             zone_name='Zone',bank_id='B1',hours=1,scheduled_seconds=3600,available_seconds=3600,
             income=10,contribution=8,wagers=100,costs=2,peer_income_rate=20,peer_contribution_rate=18,peer_wager_rate=200),
        dict(machine_id='M1',gaming_date=date(2025,1,2),month_start=pd.Timestamp('2025-01-01'),
             zone_name='Zone',bank_id='B1',hours=3,scheduled_seconds=10800,available_seconds=10800,
             income=90,contribution=84,wagers=900,costs=6,peer_income_rate=float('nan'),
             peer_contribution_rate=float('nan'),peer_wager_rate=float('nan')),
    ])
    machines,_=summary.summarize(data)
    row=machines.iloc[0]
    assert row.income_rate==25  # (10+90)/(1+3), not average daily rates
    assert row.contribution_rate==23
    assert row.income_gap==-10  # only the covered first day
    assert row.peer_coverage==.25
    assert row.measured==0  # no monthly claim from one peer-covered day
    assert 'Peer comparison unavailable' not in summary.evidence(row)


def test_missing_peer_coverage_never_becomes_a_negative_gap():
    data=pd.DataFrame([dict(machine_id='M',gaming_date=date(2025,1,1),month_start=pd.Timestamp('2025-01-01'),
        zone_name='Z',bank_id='B',hours=1,scheduled_seconds=3600,available_seconds=3600,
        income=-5,contribution=-7,wagers=100,costs=2,peer_income_rate=float('nan'),
        peer_contribution_rate=float('nan'),peer_wager_rate=float('nan'))])
    machines,_=summary.summarize(data)
    row=machines.iloc[0]
    assert row.income_rate==-5  # genuine negative earnings are preserved
    assert pd.isna(row.income_gap)
    assert 'Peer comparison unavailable' in summary.evidence(row)


def test_audited_cohort_is_not_replaced_by_a_raw_earnings_ranking(monkeypatch):
    machines=pd.DataFrame([
        dict(machine_id='raw-lowest',hours=20,rank=1,contribution_rate=-5),
        dict(machine_id='candidate',hours=20,rank=2,contribution_rate=5),
    ])
    result=dict(selected=[dict(machine_id='candidate',replacement_rank=1)],
        rows=[dict(machine_id='raw-lowest'),dict(machine_id='candidate')])
    monkeypatch.setattr(summary,'selection_audit',lambda *args:result)
    monkeypatch.setattr(summary,'_db_stamp',lambda:0)
    shortlist,_,_=summary.audited_selection(machines,Filters())
    assert shortlist.machine_id.tolist()==['candidate']
    assert shortlist['rank'].tolist()==[1]
    local,_,title=summary.audited_selection(machines,Filters(zone='Z1'))
    assert local.machine_id.tolist()==['raw-lowest','candidate']
    assert local.audit_status.tolist()==['Not shortlisted','Candidate #1']
    assert 'Local comparison' in title
