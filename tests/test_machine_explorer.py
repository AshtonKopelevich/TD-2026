"""Observed indicators, gaming-day repair boundaries and interactive map semantics."""

from datetime import date

import pandas as pd

from dashboard import machine_explorer as explorer
from dashboard.data import Filters


def test_indicators_overlap_but_do_not_diagnose_above_peer_earners():
    baseline=dict(income_gap=-2,peer_coverage=1,covered_day=181,wager_ratio=.7,
        measured=6,below=5,availability=.9,repair_changes=1,days=181)
    data=pd.DataFrame([baseline,dict(baseline,income_gap=2),dict(baseline,covered_day=5,days=5)])
    result=explorer.add_indicators(data)
    keys=[key for key,_,_ in explorer.UNDERPERFORMANCE_INDICATORS]
    assert result.iloc[0][keys].all()
    assert not result.iloc[1][keys].any()
    assert not result.iloc[2][keys].any()
    assert '5 active days' in result.iloc[2].data_notice
    assert result.iloc[1].indicator_labels==''
    assert 'Luck' not in result.iloc[0].indicator_labels


def test_repairs_use_actual_income_and_local_six_am_boundary(monkeypatch):
    daily=pd.DataFrame([dict(machine_id='M1',gaming_date=d,location_id='L1',config_id='C1',
        hours=24,scheduled_seconds=86400,calendar_day_seconds=86400,
        income=240 if d.day<8 else 480) for d in pd.date_range('2025-01-01','2025-01-15')])
    # Jan 9 at 02:00 Pacific belongs to the Jan 8 gaming date. Seven
    # subsequent dates Jan 9-15 must remain available for the comparison.
    ticket=pd.DataFrame([dict(operation_id='T1',machine_id='M1',gaming_date=pd.Timestamp('2025-01-08'),
        available_at_utc=pd.Timestamp('2025-01-09 10:00:00'),comparison_status='comparable')])
    monkeypatch.setattr(explorer,'query',lambda *args:ticket)
    result=explorer.repair_comparisons(daily,Filters())
    assert len(result)==1
    assert result.iloc[0].before==10
    assert result.iloc[0].after==20
    assert result.iloc[0].relative==1
    assert result.iloc[0].flagged
    moved=daily.copy()
    moved.loc[moved.gaming_date>pd.Timestamp('2025-01-08'),'location_id']='L2'
    assert explorer.repair_comparisons(moved,Filters()).empty


def test_map_uses_end_of_period_positions_and_local_machine_links(monkeypatch):
    rows=pd.DataFrame([
        dict(machine_id='current',gaming_date=pd.Timestamp('2025-06-30'),x_m=10,y_m=20,
            zone_name='Zone',bank_id='B1',income=100,income_rate=2,availability=.9,
            indicator_labels='Low actual earnings',low_earnings=True),
        dict(machine_id='retired',gaming_date=pd.Timestamp('2025-05-01'),x_m=10,y_m=20,
            zone_name='Zone',bank_id='B1',income=50,income_rate=1,availability=1,
            indicator_labels='',low_earnings=False),
    ])
    monkeypatch.setattr(explorer,'query',lambda *args:pd.DataFrame({'d':[pd.Timestamp('2025-06-30')]}))
    chart=explorer.floor_map(rows,Filters(zone='Z1',bank='B1'))
    assert len(chart.fig.data[0].x)==1
    assert chart.fig.data[0].customdata[0][0]=='current'
    assert chart.fig.data[0].customdata[0][1]=='/machines/current?zone=Z1&bank=B1'
    assert chart.extra['click_href_index']==1
    assert '1 mapped machines' in chart.subtitle


def test_table_order_is_actual_house_win_not_theoretical_reference():
    rows=[]
    for mid,income,theoretical in [('High',100,1),('Low',-20,999999)]:
        rows.append(dict(machine_id=mid,zone_name='Zone',bank_id='B1',manufacturer='Maker',theme='Game',
            days=90,wagers=500,income=income,income_rate=income/90,contribution=income-10,
            contribution_rate=(income-10)/90,income_gap=-1,availability=1,indicator_labels='',data_notice='',
            theoretical=theoretical))
    rendered=str(explorer.observed_table(pd.DataFrame(rows),Filters()))
    assert rendered.index('/machines/Low')<rendered.index('/machines/High')
    assert 'Theoretical' not in rendered
    assert 'Diagnosis' not in rendered
