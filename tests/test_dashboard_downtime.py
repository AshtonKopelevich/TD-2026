"""Downtime estimate coverage and understandable operation-type statistics."""

from datetime import date

import pandas as pd

from dashboard.downtime_view import headline, monthly_losses, operations_panel
from dashboard.data import Filters


def test_monthly_losses_preserve_missing_estimates_and_report_coverage():
    data=pd.DataFrame([
        dict(gaming_date=pd.Timestamp('2025-01-01'),downtime_seconds=3600,
             estimated_lost_theo_usd=10,lost_theo_low_usd=5,lost_theo_high_usd=20),
        dict(gaming_date=pd.Timestamp('2025-01-02'),downtime_seconds=7200,
             estimated_lost_theo_usd=None,lost_theo_low_usd=None,lost_theo_high_usd=None),
        dict(gaming_date=pd.Timestamp('2025-02-01'),downtime_seconds=3600,
             estimated_lost_theo_usd=None,lost_theo_low_usd=None,lost_theo_high_usd=None),
    ])
    monthly=monthly_losses(data)
    assert monthly.iloc[0].estimated_lost_theo_usd==10
    assert monthly.iloc[0].downtime_hours==3
    assert monthly.iloc[0].coverage==1/3
    assert pd.isna(monthly.iloc[1].estimated_lost_theo_usd)
    assert monthly.iloc[1].coverage==0
    assert 'could not be estimated' in headline(Filters(),data.iloc[2:])


def test_shift_headline_includes_local_working_hours():
    data=pd.DataFrame([dict(estimated_lost_theo_usd=100,lost_theo_low_usd=50,lost_theo_high_usd=200,shift='Swing')])
    text=headline(Filters(),data)
    assert '2–10 p.m. local time' in text
    assert 'Lost Expected Value' in text
    assert 'theo' not in text.lower()


def test_operation_cards_keep_minor_types_and_missing_durations_visible():
    data=pd.DataFrame([
        dict(event_type='fault_repair',direct_cost_usd=100,response_hours=0,repair_hours=2),
        dict(event_type='move',direct_cost_usd=200,response_hours=None,repair_hours=None),
    ])
    panel=str(operations_panel(data))
    assert 'Fault repair' in panel and 'Move' in panel and 'Install' in panel
    assert panel.count('50.0% of all tickets')==2
    assert '$100' in panel and '$200' in panel
    assert '120 min' in panel and '0 min' in panel
