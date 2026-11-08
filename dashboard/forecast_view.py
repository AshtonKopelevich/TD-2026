"""Explain the saved forecasting calculation without refitting the model."""

from decimal import Decimal, ROUND_HALF_UP
import html

import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

from .charts import BLUE, ORANGE, MUTED, GRID, INK, AXIS, BAND, Chart, figure, fmt_money, fmt_num, fmt_short_money, table
from .data import T, query


WEEKDAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
METHODS={'weekday_mean':'Weekday averages','calendar_regression':'Calendar regression'}


def timeline_chart(fc):
    fig=figure(height=390,hovermode='x unified')
    fig.add_trace(go.Scatter(x=fc.forecast_date,y=fc.actual_coin_in_usd,name='Actual wagering',
        mode='lines',line=dict(color=INK,width=1.5),connectgaps=False,
        hovertemplate='Actual wagers: $%{y:,.0f}<extra></extra>'))
    historical=fc[fc.split.isin(['validation','test'])]
    future=fc[fc.split=='future']
    fig.add_trace(go.Scatter(x=historical.forecast_date,y=historical.model_prediction_usd,name='Saved historical predictions',
        mode='lines',line=dict(color=BLUE,width=2),connectgaps=False,
        hovertemplate='Prediction: $%{y:,.0f}<extra></extra>'))
    fig.add_trace(go.Scatter(x=future.forecast_date,y=future.model_prediction_usd,name='July forecast',
        mode='lines',line=dict(color=ORANGE,width=2,dash='dash'),
        hovertemplate='July forecast: $%{y:,.0f}<extra></extra>'))
    fig.add_trace(go.Scatter(x=fc.forecast_date,y=fc.baseline_prediction_usd,name='Constant-mean baseline (optional)',
        mode='lines',line=dict(color=MUTED,width=1,dash='dot'),visible='legendonly',connectgaps=False,
        hovertemplate='Constant-mean baseline: $%{y:,.0f}<extra></extra>'))
    names={'train':'Training','validation':'Selection','test':'Holdout','future':'July forecast'}
    for split,g in fc.groupby('split',sort=False):
        start,end=g.forecast_date.min(),g.forecast_date.max()
        if split in ['test','future']:
            fig.add_vrect(x0=start,x1=end,fillcolor=BAND,line_width=0,layer='below')
        if split!='train':
            fig.add_vline(x=start,line=dict(color=AXIS,width=1,dash='dot'))
        fig.add_annotation(x=start+(end-start)/2,y=1.02,xref='x',yref='paper',text=names.get(split,split),
            showarrow=False,yanchor='bottom',font=dict(size=10,color=MUTED))
    fig.update_layout(xaxis=dict(title_text='Gaming date',tickformat='%b'),
        yaxis=dict(title_text='Daily total wagers ($)',tickprefix='$',showgrid=True,gridcolor=GRID),margin=dict(t=78))
    numbers=fc[['forecast_date','split','actual_coin_in_usd','model_prediction_usd','baseline_prediction_usd']].copy()
    numbers['split']=numbers['split'].map(names)
    numbers.columns=['Gaming date','Model stage','Actual wagers','Saved prediction','Constant-mean baseline']
    return Chart('forecast-main','Predicted and actual wagering over time',fig,'Saved forecasts and observed daily wagering',
        subtitle='Actual wagering through June, historical predictions for April–June, and the July forecast. January–March has no published predictions; July has no observed results. Click the optional baseline in the legend to show it.',
        table=table(numbers,{'Gaming date':lambda v:v.strftime('%b %d, %Y'),'Actual wagers':fmt_money,
            'Saved prediction':fmt_money,'Constant-mean baseline':fmt_money}),wide=True)


def reconstruct(method,parameters,future,features):
    """Reproduce the saved July calculations, including clipping and cent rounding."""
    p=dict(zip(parameters.parameter,parameters.value))
    rows=[]
    feature_lookup=features.set_index('forecast_date')
    for row in future.itertuples():
        weekday=row.forecast_date.dayofweek
        if method=='weekday_mean':
            value=p[f'weekday_{weekday}']
            base=value
            adjustment=0
        elif method=='calendar_regression':
            flags=feature_lookup.loc[row.forecast_date]
            base=p['intercept']
            adjustment=(p[WEEKDAYS[weekday]] if weekday else 0)+sum(p[key]*int(flags[key]) for key in ['holiday','city_event','property_event'])
            value=base+adjustment
        else:
            raise ValueError(f'Unsupported saved forecast method: {method}')
        rounded=Decimal(str(max(0.0,float(value)))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if rounded!=Decimal(str(row.model_prediction_usd)).quantize(Decimal('.01')):
            raise ValueError(f'Saved forecast reconstruction mismatch on {row.forecast_date}')
        rows.append(dict(date=row.forecast_date,weekday=WEEKDAYS[weekday],base=base,adjustment=adjustment,prediction=float(rounded)))
    return pd.DataFrame(rows,columns=['date','weekday','base','adjustment','prediction'])


def validation_block(fc):
    scored=fc[fc.evaluation_eligible.fillna(False)&fc.actual_coin_in_usd.notna()].copy()
    scored['model_error']=(scored.model_prediction_usd-scored.actual_coin_in_usd).abs()
    scored['baseline_error']=(scored.baseline_prediction_usd-scored.actual_coin_in_usd).abs()
    results=scored.groupby('split',sort=False).agg(start=('forecast_date','min'),end=('forecast_date','max'),
        days=('forecast_date','count'),model=('model_error','mean'),baseline=('baseline_error','mean'),
        fit_start=('fit_start','first'),fit_end=('fit_end','first'),frozen=('prediction_frozen_at_utc','first')).reset_index()
    results['split']=results['split'].map({'validation':'April: model selection','test':'May–June: frozen holdout'})
    results.columns=['Evaluation period','From','To','Scored days','Model mean absolute error','Baseline mean absolute error',
        'Fit from','Fit through','Predictions frozen (UTC)']
    formats={c:lambda v:v.strftime('%b %d, %Y') if pd.notna(v) else '–' for c in ['From','To','Fit from','Fit through']}
    formats.update({'Scored days':fmt_num,'Model mean absolute error':fmt_money,'Baseline mean absolute error':fmt_money,
        'Predictions frozen (UTC)':lambda v:v.strftime('%Y-%m-%d %H:%M') if pd.notna(v) else '–'})
    numbers=scored[['forecast_date','actual_coin_in_usd','model_prediction_usd','baseline_prediction_usd']].copy()
    numbers.columns=['Gaming date','Actual wagers','Model prediction','Constant-mean baseline']
    return (Markup('<details class="selection-method forecast-validation"><summary>Validation: holdout protocol and baseline comparison</summary>'
        '<p>Architecture selected using April only, after fitting both candidates on January–March. '
        'The chosen method was refit on January–April, then predictions were frozen before May–June evaluation. '
        'Baseline = the constant mean of training-period daily wagers. Mean absolute error is the average dollar distance '
        'between predictions and observed daily wagers. Build timestamps document this retrospective procedure, not forecasts made in 2025.</p>')+
        table(results,formats,sortable=False)+table(numbers,{'Gaming date':lambda v:v.strftime('%b %d, %Y'),
            'Actual wagers':fmt_money,'Model prediction':fmt_money,'Constant-mean baseline':fmt_money})+
        Markup('</details>'))


def build(f):
    fc=query(f'SELECT * FROM {T("mart_forecast")} ORDER BY forecast_date')
    future=fc[fc.split=='future'].copy()
    if future.empty:
        return dict(title_override='Forecast',compact=True,headline='',no_filters=True,
            scope_note='Property-wide forecast; no July predictions are available.',sections=[])
    method=str(future.model_method.iloc[0])
    parameters=query('SELECT * FROM diagnostics.forecast_parameters WHERE split=? AND method=?',['future',method])
    features=query('SELECT * FROM diagnostics.forecast_features WHERE split=?',['future'])
    if parameters.empty:
        raise ValueError('Saved forecast parameters are required to explain this model.')
    start=pd.Timestamp(parameters.fit_start.iloc[0])
    end=pd.Timestamp(parameters.fit_end.iloc[0])
    history=fc[(fc.forecast_date>=start)&(fc.forecast_date<=end)&fc.actual_coin_in_usd.notna()].copy()
    history['weekday']=history.forecast_date.dt.day_name()
    grouped=history.groupby('weekday').agg(days=('actual_coin_in_usd','count'),
        total=('actual_coin_in_usd','sum'),mean=('actual_coin_in_usd','mean')).reindex(WEEKDAYS).reset_index()
    calculated=reconstruct(method,parameters,future,features)
    method_label=METHODS.get(method,method.replace('_',' ').capitalize())

    fig=figure(height=340)
    fig.add_trace(go.Scatter(x=history.weekday,y=history.actual_coin_in_usd,name='Observed daily wagering',mode='markers',
        marker=dict(color=BLUE,size=6,opacity=.45),customdata=history.forecast_date.dt.strftime('%b %d'),
        hovertemplate='%{customdata} · %{x}<br>Actual wagers: $%{y:,.0f}<extra></extra>'))
    fig.add_trace(go.Scatter(x=grouped.weekday,y=grouped['mean'],name='Weekday arithmetic mean',mode='markers',
        marker=dict(color=ORANGE,size=13,symbol='diamond'),
        hovertemplate='%{x}<br>Mean observed wagers: $%{y:,.0f}<extra></extra>'))
    fig.update_layout(xaxis=dict(categoryorder='array',categoryarray=WEEKDAYS),
        yaxis=dict(title_text='Observed daily wagers ($)',tickprefix='$',showgrid=True,gridcolor=GRID))
    history_table=history[['forecast_date','weekday','actual_coin_in_usd']].copy()
    history_table.columns=['Gaming date','Weekday','Actual wagers']
    inputs=Chart('forecast-inputs','Historical daily wagering by weekday',fig,'Observed daily floor wagering',
        subtitle=f'Each dot is a gaming day from {start:%b %d}–{end:%b %d, %Y}. Diamonds show weekday averages.',
        table=table(history_table,{'Gaming date':lambda v:v.strftime('%b %d'),'Actual wagers':fmt_money}),wide=True)

    fig2=figure(height=320,legend=False)
    if method=='weekday_mean':
        saved=parameters.set_index('parameter').value
        grouped['fitted']=[saved[f'weekday_{i}'] for i in range(7)]
        # Verify the explanation's training sums reproduce the saved coefficients.
        if ((grouped['mean']-grouped.fitted).abs()>1e-6).any():
            raise ValueError('Historical weekday means do not reproduce the saved July model.')
        fig2.add_trace(go.Bar(x=grouped.weekday,y=grouped.fitted,marker_color=BLUE,
            customdata=grouped[['total','days']],
            hovertemplate='%{x}<br>Total wagers: $%{customdata[0]:,.0f}<br>Gaming days: %{customdata[1]}<br>Mean = $%{y:,.2f}<extra></extra>'))
        formula_table=grouped[['weekday','total','days','fitted']].copy()
        formula_table.columns=['Weekday','Historical total wagers','Gaming days','Weekday mean used for July']
        formula_formats={'Historical total wagers':fmt_money,'Gaming days':fmt_num,'Weekday mean used for July':lambda v:fmt_money(v,2)}
        title='Calculate each weekday’s forecast value'
        subtitle='Weekday value = total observed wagers on that weekday ÷ number of matching gaming days. July dates use this lookup; holidays and events are not inputs to the selected weekday-average model.'
    else:
        names={'intercept':'Monday base','holiday':'Holiday adjustment','city_event':'Announced city event','property_event':'Announced property event'}
        formula_table=parameters[['parameter','value']].copy()
        formula_table['parameter']=formula_table.parameter.map(lambda value:names.get(value,value+' adjustment'))
        formula_table.columns=['Model term','Fitted dollars']
        formula_formats={'Fitted dollars':lambda v:fmt_money(v,2)}
        fig2.add_trace(go.Bar(x=formula_table['Fitted dollars'],y=formula_table['Model term'],orientation='h',marker_color=BLUE))
        title='Saved calendar-model coefficients'
        subtitle='Predicted wagers = Monday base + matching weekday adjustment + holiday and advance-announced event adjustments. Negative predictions are clipped to zero.'
    fig2.update_layout(yaxis=dict(title_text='Fitted daily wagers ($)' if method=='weekday_mean' else 'Model term'),
        xaxis=dict(title_text='Weekday' if method=='weekday_mean' else 'Dollar adjustment'))
    calculation=Chart('forecast-calculation',title,fig2,'Saved final-model parameters',
        subtitle=subtitle,table=table(formula_table,formula_formats))

    july_fig=figure(height=350,legend=False)
    july_fig.add_trace(go.Bar(x=calculated.date,y=calculated.prediction,marker_color=BLUE,
        customdata=calculated.weekday,
        hovertemplate='%{x|%b %d, %Y} · %{customdata}<br>Predicted wagers: $%{y:,.0f}<extra></extra>'))
    july_fig.update_layout(xaxis=dict(title_text='Forecast gaming date',tickformat='%b %d'),
        yaxis=dict(title_text='Predicted total wagers ($)',tickprefix='$',rangemode='tozero'))
    jt=calculated.copy()
    jt.columns=['Forecast gaming date','Weekday','Weekday lookup value' if method=='weekday_mean' else 'Base value',
        'Calendar adjustment','Predicted total wagers']
    if method=='weekday_mean':
        jt=jt.drop(columns='Calendar adjustment')
    july=Chart('forecast-july','Predicted daily wagering · July 1–30, 2025',july_fig,'Saved July forecast',wide=True,
        subtitle='Each bar predicts dollars wagered across the entire floor, including re-wagered winnings. This is a forecast of play volume, not casino earnings or profit. No proposed action uplift is included.',
        table=table(jt,{'Forecast gaming date':lambda v:v.strftime('%b %d, %Y'),
            **{c:lambda v:fmt_money(v,2) for c in jt.columns if c not in ['Forecast gaming date','Weekday']}}))
    pipeline=Markup('<ol class="forecast-pipeline">'+''.join(
        f'<li><strong>{html.escape(label)}</strong><span>{html.escape(dates)}</span><small>{html.escape(note)}</small></li>'
        for label,dates,note in [
            ('Fit candidates','January–March','Weekday averages and calendar regression'),
            ('Select method','April',method_label+' selected'),
            ('Frozen evaluation','May–June','Refit on January–April; no holdout refitting'),
            ('Refit selected method','January–June','All available historical wagering'),
            ('Generate predictions','July 1–30','Saved calendar inputs and fitted parameters')])+'</ol>')
    total=calculated.prediction.sum()
    return dict(title_override='Forecast',compact=True,headline='',no_filters=True,
        scope_note='Property-wide forecast · fitted through June 30, 2025 · July estimates are not observed results.',
        rail=[dict(label='Selected method',value=method_label,sub='Selected using April only'),
            dict(label='Historical fit',value='Jan–Jun',sub=f'{len(history)} observed gaming days'),
            dict(label='Forecast horizon',value=f'{len(calculated)} days',sub='July 1–30, 2025'),
            dict(label='Predicted total wagers',value=fmt_short_money(total),sub='July forecast; no action uplift'),
            dict(label='Predicted daily average',value=fmt_short_money(calculated.prediction.mean()),sub='Wagering volume, not profit')],
        sections=[dict(charts=[timeline_chart(fc)]),dict(title='How the forecast is generated',blocks=[pipeline]),dict(charts=[inputs,calculation,july]),
            dict(title='Validation details',blocks=[validation_block(fc)],source='Frozen forecasts and observed wagering')])
