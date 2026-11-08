"""Auditable rolling compensation rates for loyalty-card activity only."""

import pandas as pd
import numpy as np


def rolling_rates(daily):
    data=daily.sort_values('gaming_date').copy()
    for source,target in [('comp_cost_usd','cost7'),('actual_tracked_loss_usd','loss7'),('tracked_coin_in_usd','wagers7')]:
        values=data.set_index('gaming_date')[source].rolling('7D',min_periods=1).sum()
        data[target]=values.to_numpy()
    data['per_loss7']=data.cost7/data.loss7.where(data.loss7>0)
    data['per_coin7']=data.cost7/data.wagers7.where(data.wagers7>0)
    data['window_start']=data.gaming_date.to_numpy(dtype='datetime64[ns]')-np.timedelta64(6,'D')
    if not data.empty:
        data['window_start']=data.window_start.clip(lower=data.gaming_date.iloc[0])
    data['window_days']=(data.gaming_date-data.window_start).dt.days+1
    return data
