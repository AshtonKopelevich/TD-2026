"""Known-answer checks for the proposed read-only replacement evidence audit."""

import pytest

from casino_pipeline.analysis.replacements import lease_scenario, selection_reasons


def candidate():
    return dict(current_machine=True,active_days=181,positive_wager_days=181,
        peer_coverage_fraction=1,peer_coin_in_rate_ratio=.7,peer_rate_ratio=.7,
        persistent_months=5,weak_in_final_month=True,location_flag=False,
        downtime_flag=False,repair_rebound_flag=None,hold_anomaly_flag=False,
        dependence_warning=False,exposure_concentration_warning=False,
        method_disagreement=False,expected_contribution_per_available_hour=5)


def test_retired_and_nonpersistent_machines_cannot_qualify():
    row=candidate()
    assert selection_reasons(row)==[]
    assert 'not active at historical end' in selection_reasons(dict(row,current_machine=False))
    assert 'weakness not persistent through final month' in selection_reasons(dict(row,weak_in_final_month=False))
    assert 'weakness not persistent through final month' in selection_reasons(dict(row,persistent_months=3))
    assert 'method_disagreement' in selection_reasons(dict(row,method_disagreement=True))


def test_missing_peer_evidence_is_not_a_zero_gap():
    row=candidate()
    assert 'insufficient peer coverage' in selection_reasons(dict(row,peer_coverage_fraction=None))
    assert selection_reasons(dict(row,peer_rate_ratio=None))


def test_lease_lead_time_installation_and_no_credited_fixed_cost_savings():
    action=dict(lead_days=14,downtime_minutes=360,unit_cost_cents=250000,recurring_cost_cents_per_day=5500)
    row=dict(availability_ratio=1,peer_theo_per_hour=20,theo_per_available_hour=10)
    result=lease_scenario(row,action,1)
    assert result['cash_cost_usd']==3380
    assert result['productive_hours']==378
    assert result['net_scenario_usd']==340  # 378*10 - 6*10 - 3380
    assert result['break_even_theo_uplift_per_hour']==pytest.approx(3440/378)
    assert lease_scenario(row,action,0)['net_scenario_usd']==-3440
    assert lease_scenario(row,dict(action,lead_days=30),1)['net_scenario_usd']==-2500
