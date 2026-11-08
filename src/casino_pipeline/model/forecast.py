"""Leakage-controlled calendar forecasting; only April selects the architecture."""

from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path

import numpy as np

from .. import constants as c
from ..descriptive import MartContract,check_query,validate_contract
from ..machine_daily import MONEY

FORECAST = MartContract('mart_forecast',('forecast_date',),{
    'forecast_date':'DATE','split':'VARCHAR',
    **dict.fromkeys(('actual_coin_in_usd','model_prediction_usd','baseline_prediction_usd'),MONEY),
    'model_method':'VARCHAR','fit_start':'DATE','fit_end':'DATE','forecast_origin':'DATE',
    'prediction_frozen_at_utc':'TIMESTAMP','evaluation_eligible':'BOOLEAN','weekday_index':'BIGINT',
},frozenset('actual_coin_in_usd model_prediction_usd baseline_prediction_usd fit_start fit_end forecast_origin prediction_frozen_at_utc'.split()))
CONTRACTS = (FORECAST,)
FEATURES = ('intercept','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday','holiday','city_event','property_event')


def days(start,end):
    return [start+timedelta(days=i) for i in range((end-start).days+1)]


def money(value):
    return Decimal(str(float(value))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def calendar_features(dates,origin,events,holidays):
    known = [e for e in events if e[2] is not None and e[2]<=origin]
    return np.asarray([[1.0]+[float(d.weekday()==w) for w in range(1,7)]+
        [float(d in holidays),float(any(a<=d<=b and scope=='citywide' for a,b,_,scope in known)),
         float(any(a<=d<=b and scope=='property' for a,b,_,scope in known))] for d in dates],dtype=float)


def fit_model(method,dates,target,origin,events,holidays):
    y = np.asarray(target,dtype=float)
    if not len(y) or not np.isfinite(y).all() or (y<0).any():
        raise ValueError('Forecast training targets must be finite nonnegative amounts')
    if method=='weekday_mean':
        means = [float(np.mean([v for d,v in zip(dates,y) if d.weekday()==w]))
                 if any(d.weekday()==w for d in dates) else float(y.mean()) for w in range(7)]
        return means
    x = calendar_features(dates,origin,events,holidays)
    return np.linalg.lstsq(x,y,rcond=None)[0].tolist()


def predict(method,parameters,dates,origin,events,holidays):
    if method=='weekday_mean':
        values = [parameters[d.weekday()] for d in dates]
    else:
        values = calendar_features(dates,origin,events,holidays)@np.asarray(parameters)
    return [money(max(0.0,float(v))) for v in values]


def build_forecast(con):
    start = date.fromisoformat(c.ANALYSIS_START)
    fit_end = date.fromisoformat(c.FORECAST_SELECTION_FIT_END)
    validation_start,validation_end = map(date.fromisoformat,(c.FORECAST_VALIDATION_START,c.FORECAST_VALIDATION_END))
    test_start,test_end = map(date.fromisoformat,(c.FORECAST_TEST_START,c.FORECAST_TEST_END))
    future_start,future_end = map(date.fromisoformat,(c.FORECAST_START,c.FORECAST_END))
    if not (start<=fit_end and validation_start==fit_end+timedelta(days=1) and validation_end>=validation_start
            and test_start==validation_end+timedelta(days=1) and test_end>=test_start
            and future_start==test_end+timedelta(days=1) and future_end>=future_start
            and date.fromisoformat(c.ANALYSIS_END)==test_end):
        raise ValueError('Forecast folds must be consecutive and fit the configured analysis window')
    events = con.execute('SELECT start_date,end_date,announced_date,local_scope FROM raw.events').fetchall()
    holidays = {d for d,name in con.execute('SELECT gaming_date,federal_holiday FROM raw.calendar_day').fetchall() if name and name.strip()}
    holidays.update(date.fromisoformat(d) for d in c.FORECAST_FUTURE_HOLIDAYS)
    con.execute('''CREATE TABLE diagnostics.forecast_frozen_predictions (
      forecast_date DATE,split VARCHAR,model_method VARCHAR,model_prediction_usd DECIMAL(24,2),
      baseline_prediction_usd DECIMAL(24,2),fit_start DATE,fit_end DATE,forecast_origin DATE,prediction_frozen_at_utc TIMESTAMP)''')
    con.execute('''CREATE TABLE diagnostics.forecast_parameters (
      split VARCHAR,method VARCHAR,parameter VARCHAR,value DOUBLE,fit_start DATE,fit_end DATE)''')
    con.execute('''CREATE TABLE diagnostics.forecast_features (
      forecast_date DATE,split VARCHAR,forecast_origin DATE,holiday BOOLEAN,city_event BOOLEAN,property_event BOOLEAN)''')

    def load_target(end):
        rows = con.execute('''SELECT gaming_date,coin_in_usd FROM marts.mart_floor_daily
          WHERE gaming_date BETWEEN ? AND ? ORDER BY gaming_date''',[start,end]).fetchall()
        if [r[0] for r in rows]!=days(start,end):
            raise ValueError(f'Incomplete forecast fit history through {end}')
        return [r[0] for r in rows],[float(r[1]) for r in rows]

    def freeze(method,split,train_end,pred_dates):
        train_dates,y = load_target(train_end)  # Query cannot retrieve later targets.
        parameters = fit_model(method,train_dates,y,train_end,events,holidays)
        predictions = predict(method,parameters,pred_dates,train_end,events,holidays)
        baseline = money(float(np.mean(y)))
        frozen = datetime.now(timezone.utc).replace(tzinfo=None)
        con.executemany('INSERT INTO diagnostics.forecast_frozen_predictions VALUES (?,?,?,?,?,?,?,?,?)',[
            (d,split,method,p,baseline,start,train_end,train_end,frozen) for d,p in zip(pred_dates,predictions)])
        names = [f'weekday_{i}' for i in range(7)] if method=='weekday_mean' else FEATURES
        con.executemany('INSERT INTO diagnostics.forecast_parameters VALUES (?,?,?,?,?,?)',[
            (split,method,name,float(value),start,train_end) for name,value in zip(names,parameters)]+
            [(split,'constant_mean','intercept',float(baseline),start,train_end)])
        feature_rows = calendar_features(pred_dates,train_end,events,holidays)
        if con.execute('SELECT count(*) FROM diagnostics.forecast_features WHERE split=?',[split]).fetchone()[0]==0:
            con.executemany('INSERT INTO diagnostics.forecast_features VALUES (?,?,?,?,?,?)',[
                (d,split,train_end,bool(x[-3]),bool(x[-2]),bool(x[-1])) for d,x in zip(pred_dates,feature_rows)])

    for method in ('weekday_mean','calendar_regression'):
        freeze(method,'validation',fit_end,days(validation_start,validation_end))
    # Only April actuals are exposed to selection, after candidate predictions exist.
    con.execute('''CREATE TABLE diagnostics.forecast_candidates AS
      SELECT f.*,a.coin_in_usd::DECIMAL(24,2) AS actual_coin_in_usd,
        abs(f.model_prediction_usd-a.coin_in_usd)::DOUBLE AS absolute_error_usd
      FROM diagnostics.forecast_frozen_predictions f JOIN marts.mart_floor_daily a ON a.gaming_date=f.forecast_date
      WHERE f.split='validation' ''')
    scores = con.execute('''SELECT model_method,avg(absolute_error_usd) AS mae FROM diagnostics.forecast_candidates
      GROUP BY model_method ORDER BY mae,CASE WHEN model_method='weekday_mean' THEN 0 ELSE 1 END''').fetchall()
    if len(scores)!=2:
        raise ValueError('Both forecasting candidates require April validation observations')
    winner = scores[0][0]
    freeze(winner,'test',validation_end,days(test_start,test_end))
    # Freeze is a committed database table before this evaluation query reads holdout actuals.
    con.execute('''CREATE TABLE diagnostics.forecast_evaluation AS
      WITH errors AS (
        SELECT f.split,f.model_method AS method,(isodow(f.forecast_date)-1)::BIGINT AS weekday_index,
          abs(f.model_prediction_usd-a.coin_in_usd)::DOUBLE AS absolute_error_usd
        FROM diagnostics.forecast_frozen_predictions f JOIN marts.mart_floor_daily a ON a.gaming_date=f.forecast_date
        UNION ALL SELECT f.split,'constant_mean',(isodow(f.forecast_date)-1)::BIGINT,
          abs(f.baseline_prediction_usd-a.coin_in_usd)::DOUBLE
        FROM diagnostics.forecast_frozen_predictions f JOIN marts.mart_floor_daily a ON a.gaming_date=f.forecast_date
        WHERE f.model_method=? OR f.split='test'
      ) SELECT split,method,weekday_index,count(*)::BIGINT AS observations,avg(absolute_error_usd)::DOUBLE AS mae_usd
      FROM errors GROUP BY GROUPING SETS ((split,method,weekday_index),(split,method))''',[winner])
    freeze(winner,'future',test_end,days(future_start,future_end))
    # All targets below are joined for display after model selection and prediction freeze.
    sql = Path(__file__).resolve().parents[3]/'sql'/'marts'/'forecast.sql'
    con.execute(sql.read_text(encoding='utf-8'),[start,future_end,winner,winner])
    con.execute('''CREATE TABLE diagnostics.forecast_selection AS
      SELECT ?::VARCHAR AS selected_method,?::DATE AS selection_fit_end,?::DATE AS selection_validation_end,
        model.mae_usd AS test_model_mae_usd,baseline.mae_usd AS test_baseline_mae_usd,
        model.mae_usd<baseline.mae_usd AS beats_baseline,
        (baseline.mae_usd-model.mae_usd)/nullif(baseline.mae_usd,0) AS test_improvement_fraction,
        'Architecture selected on April only. July refits Jan-Jun; no holdout-based reselection. Future event flags reflect supplied coverage.'::VARCHAR AS limitation
      FROM diagnostics.forecast_evaluation model CROSS JOIN diagnostics.forecast_evaluation baseline
      WHERE model.split='test' AND model.method=? AND model.weekday_index IS NULL
        AND baseline.split='test' AND baseline.method='constant_mean' AND baseline.weekday_index IS NULL''',
      [winner,fit_end,validation_end,winner])


def validate_forecast(con):
    checks = validate_contract(con,FORECAST)
    queries = {
      'coverage':f"SELECT abs((SELECT count(*) FROM marts.mart_forecast)-date_diff('day',DATE '{c.ANALYSIS_START}',DATE '{c.FORECAST_END}')-1)",
      'freeze_and_leakage':'''SELECT count(*) FROM marts.mart_forecast WHERE
        (split IN ('validation','test','future') AND (model_prediction_usd IS NULL OR baseline_prediction_usd IS NULL
          OR prediction_frozen_at_utc IS NULL OR fit_end>=forecast_date OR forecast_origin<>fit_end))
        OR (split='train' AND (model_prediction_usd IS NOT NULL OR evaluation_eligible))
        OR (split='future' AND actual_coin_in_usd IS NOT NULL)
        OR (split<>'future' AND actual_coin_in_usd IS NULL)
        OR model_prediction_usd<0 OR baseline_prediction_usd<0''',
      'test_origin':f"SELECT count(*) FROM marts.mart_forecast WHERE split='test' AND fit_end<>DATE '{c.FORECAST_VALIDATION_END}'",
      'actuals':'''SELECT count(*) FROM marts.mart_forecast f JOIN marts.mart_floor_daily a ON a.gaming_date=f.forecast_date
        WHERE f.actual_coin_in_usd IS DISTINCT FROM a.coin_in_usd''',
      'selection':"SELECT abs((SELECT count(*) FROM diagnostics.forecast_selection)-1)",
    }
    checks.extend(check_query(con,'forecast.'+name,sql) for name,sql in queries.items())
    return checks
