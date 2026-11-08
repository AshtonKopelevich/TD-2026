"""Focused known-answer statistical checks; no earlier stage suite rebuild."""

from datetime import date,timedelta
import math

import pytest

from casino_pipeline import constants as c
from casino_pipeline.analysis.machines import (benjamini_hochberg,paired_blocks,block_interval,period_statistics,classify)


def observations(days=70):
    return [(date(2025,1,1)+timedelta(days=i),'P1',(-1.0 if (i//7)%2 else 1.0),100.0,4.0)
            for i in range(days)]


def test_clt_known_variance_eligibility_and_bh():
    assert benjamini_hochberg([0.001,0.01,0.03,0.2])==pytest.approx([0.004,0.02,0.04,0.2])
    assert benjamini_hochberg([0.001,0.01,0.7])[-1]>=0.7
    rows = [(date(2025,1,1)+timedelta(days=i),'P1',1.0,100.0,4.0) for i in range(70)]
    result = period_statistics(rows,'M1','full')
    assert result['luck_z_score']==pytest.approx(70/math.sqrt(280))
    assert result['luck_p_value']==pytest.approx(math.erfc((70/math.sqrt(280))/math.sqrt(2)))
    assert result['bootstrap_status']=='degenerate_blocks'
    assert period_statistics(rows[:10],'M1','full')['luck_p_value'] is None
    month = period_statistics(rows[:28],'M1','2025-01')
    assert month['clt_eligible'] and month['bootstrap_status']=='insufficient_blocks'


def test_block_pairing_episode_gaps_and_reproducibility(monkeypatch):
    monkeypatch.setattr(c,'BOOTSTRAP_REPLICATES',300)
    rows = observations()
    a = block_interval(rows,'M1:full',60,30)
    assert a==block_interval(rows,'M1:full',60,30)
    assert a['bootstrap_hold_gap_low']<0<a['bootstrap_hold_gap_high']
    assert a['bootstrap_valid_replicates']==300
    episodes = rows[:10]+[(r[0]+timedelta(days=2),'P2',*r[2:]) for r in rows[10:20]]
    strata = paired_blocks(episodes,7)
    assert [len(s) for s in strata]==[1,1]
    assert sum(s[:,1].sum() for s in strata)==1400


def test_classifications_keep_inspection_and_overlapping_evidence_separate():
    flags = dict(weak_demand_flag=False,location_flag=False,downtime_flag=False,
                 repair_rebound_flag=None,hold_anomaly_flag=True)
    assert classify(flags,True,False,True,False,False)[0]=='hold_inspection_lead'
    flags['downtime_flag']=True
    assert classify(flags,True,False,True,False,False)[0]=='mixed_evidence'
    assert classify(flags,False,None,True,False,False)[0]=='insufficient_evidence'
    flags.update(downtime_flag=False,hold_anomaly_flag=False)
    assert classify(flags,True,True,True,False,False)[0]=='luck_compatible'
