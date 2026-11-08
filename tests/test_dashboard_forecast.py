"""Calculation explanations must reproduce saved predictions, not illustrative fits."""

import pandas as pd
import pytest

from dashboard.forecast_view import reconstruct


def test_weekday_lookup_uses_saved_values_and_cent_rounding():
    parameters=pd.DataFrame({'parameter':[f'weekday_{i}' for i in range(7)],
        'value':[10,12.345,20,30,40,50,60]})
    future=pd.DataFrame({'forecast_date':pd.to_datetime(['2025-07-01','2025-07-02']),
        'model_prediction_usd':[12.35,20]})
    features=pd.DataFrame({'forecast_date':future.forecast_date,'holiday':[True,False],
        'city_event':[False,False],'property_event':[False,False]})
    result=reconstruct('weekday_mean',parameters,future,features)
    assert result.prediction.tolist()==[12.35,20]
    assert result.weekday.tolist()==['Tuesday','Wednesday']
    assert result.adjustment.tolist()==[0,0]  # weekday model does not use holidays
    mismatched=future.copy()
    mismatched.loc[0,'model_prediction_usd']=999
    with pytest.raises(ValueError,match='reconstruction mismatch'):
        reconstruct('weekday_mean',parameters,mismatched,features)


def test_calendar_components_include_only_matching_flags_and_clip_negative():
    parameters=pd.DataFrame({'parameter':['intercept','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday',
        'holiday','city_event','property_event'],'value':[100,20,0,0,0,0,0,30,-200,0]})
    future=pd.DataFrame({'forecast_date':pd.to_datetime(['2025-07-01','2025-07-02']),
        'model_prediction_usd':[150,0]})
    features=pd.DataFrame({'forecast_date':future.forecast_date,'holiday':[True,False],
        'city_event':[False,True],'property_event':[False,False]})
    result=reconstruct('calendar_regression',parameters,future,features)
    assert result.base.tolist()==[100,100]
    assert result.adjustment.tolist()==[50,-200]
    assert result.prediction.tolist()==[150,0]
