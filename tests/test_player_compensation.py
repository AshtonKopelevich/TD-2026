"""Compensation chart rates use auditable calendar-window sums."""

import pandas as pd
import pytest

from dashboard.player_compensation import rolling_rates


def test_compensation_rate_is_ratio_of_window_sums():
    daily=pd.DataFrame({'gaming_date':pd.date_range('2025-01-01',periods=8),
        'comp_cost_usd':[1]*7+[100],'actual_tracked_loss_usd':[100]*7+[1],
        'tracked_coin_in_usd':[1000]*8})
    result=rolling_rates(daily)
    assert result.iloc[6].cost7==7
    assert result.iloc[6].per_loss7==pytest.approx(.01)
    assert result.iloc[7].cost7==106
    assert result.iloc[7].loss7==601
    assert result.iloc[7].per_loss7==pytest.approx(106/601)
    assert result.iloc[7].per_coin7==pytest.approx(106/7000)
    assert result.iloc[7].window_start==pd.Timestamp('2025-01-02')
    assert result.iloc[7].window_days==7
    assert result.iloc[0].window_days==1


def test_zero_and_negative_loss_denominators_stay_unavailable():
    daily=pd.DataFrame({'gaming_date':pd.to_datetime(['2025-01-01','2025-01-02','2025-01-10']),
        'comp_cost_usd':[1,2,3],'actual_tracked_loss_usd':[-5,5,10],
        'tracked_coin_in_usd':[0,0,100]})
    result=rolling_rates(daily)
    assert pd.isna(result.iloc[0].per_loss7)
    assert pd.isna(result.iloc[1].per_loss7)
    assert pd.isna(result.iloc[1].per_coin7)
    # January 1-2 are outside January 10's calendar window, even though
    # fewer than seven source rows have been observed.
    assert result.iloc[2].cost7==3
    assert result.iloc[2].per_loss7==pytest.approx(.3)
    assert result.iloc[2].per_coin7==pytest.approx(.03)
