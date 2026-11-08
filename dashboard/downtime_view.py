"""Downtime estimates with explicit units, coverage and operational definitions."""

import html
import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

from .charts import BLUE, ORANGE, GRID, INK_2, SEQ_BLUE, Chart, figure, fmt_money, fmt_num, fmt_pct, fmt_short_money, table
from .contract import EVENT_TYPES


SHIFTS={'Day':'6 a.m.–2 p.m.','Swing':'2–10 p.m.','Grave':'10 p.m.–6 a.m.'}
LOSS='Lost Expected Value'


def loss_sum(values):
    return values.sum(min_count=1)


def median_minutes(values):
    known=values.dropna()
    return known.median()*60 if not known.empty else float('nan')


def headline(f,dh=None):
    if dh is None:
        from .pages import _downtime
        dh=_downtime(f)
    if dh.empty:
        return 'No recorded downtime in this selection.'
    lost=loss_sum(dh.estimated_lost_theo_usd)
    if pd.isna(lost):
        return 'Downtime was recorded; Lost Expected Value could not be estimated for this selection.'
    low,high=loss_sum(dh.lost_theo_low_usd),loss_sum(dh.lost_theo_high_usd)
    text=f'Downtime cost an estimated {fmt_short_money(lost)} in Lost Expected Value'
    if pd.notna(low) and pd.notna(high):
        text+=f' (scenario range {fmt_short_money(low)}–{fmt_short_money(high)})'
    text+='.'
    if lost>0:
        shifts=dh.groupby('shift').estimated_lost_theo_usd.sum(min_count=1).dropna()
        if not shifts.empty:
            peak=shifts.idxmax()
            text+=f' The {peak.lower()} shift ({SHIFTS[peak]} local time) accounts for {shifts.max()/lost:.0%}.'
    return text


def monthly_losses(dh):
    data=dh.assign(month=pd.to_datetime(dh.gaming_date).dt.to_period('M').dt.start_time,
        downtime_hours=dh.downtime_seconds/3600,
        estimated_hours=(dh.downtime_seconds/3600).where(dh.estimated_lost_theo_usd.notna(),0))
    amounts=data.groupby('month')[['estimated_lost_theo_usd','lost_theo_low_usd','lost_theo_high_usd']].sum(min_count=1)
    hours=data.groupby('month')[['downtime_hours','estimated_hours']].sum()
    result=amounts.join(hours).reset_index()
    result['coverage']=result.estimated_hours/result.downtime_hours.replace(0,float('nan'))
    return result


def operations_panel(t):
    cards=[]
    for code,label in EVENT_TYPES.items():
        rows=t[t.event_type==code]
        share=len(rows)/len(t) if len(t) else 0
        cost=loss_sum(rows.direct_cost_usd) if not rows.empty else 0
        cards.append(f'<article class="operation-type"><h3>{html.escape(label)}</h3>'
            f'<p class="operation-count">{len(rows):,} <small>tickets · {share:.1%} of all tickets</small></p>'
            f'<dl><dt>Direct recorded cost</dt><dd>{fmt_money(cost)}</dd>'
            f'<dt>Median wait to start</dt><dd>{fmt_num(median_minutes(rows.response_hours))} min</dd>'
            f'<dt>Median work duration</dt><dd>{fmt_num(median_minutes(rows.repair_hours))} min</dd></dl></article>')
    # Retain any future source types rather than silently omitting them.
    others=t[~t.event_type.isin(EVENT_TYPES)]
    if not others.empty:
        cards.append(f'<article class="operation-type"><h3>Other recorded operations</h3><p class="operation-count">{len(others):,} <small>tickets</small></p></article>')
    return Markup('<div class="operation-types">'+''.join(cards)+'</div>')


def build(f):
    from .pages import _downtime, _tickets
    dh=_downtime(f)
    tickets=_tickets(f)
    if f.zone:
        tickets=tickets[tickets.zone_id==f.zone]
    if f.bank:
        tickets=tickets[tickets.bank_id==f.bank]
    faults=tickets[tickets.controllable_fault.fillna(False).astype(bool)]
    lost=loss_sum(dh.estimated_lost_theo_usd) if not dh.empty else 0
    rail=[dict(label=LOSS,value=fmt_short_money(lost),sub='Estimated gross earnings foregone'),
        dict(label='Machine-hours down',value=fmt_num(dh.downtime_seconds.sum()/3600),sub=f.period_label),
        dict(label='Fault repairs',value=fmt_num(len(faults)),sub=f'{len(tickets):,} operation tickets in total'),
        dict(label='Median wait to start',value=f'{fmt_num(median_minutes(faults.response_hours))} min',sub='Ticket opened → work began'),
        dict(label='Median repair duration',value=f'{fmt_num(median_minutes(faults.repair_hours))} min',sub='Work began → machine available')]

    hours=list(range(6,24))+list(range(6))
    weekdays=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    grouped=dh.groupby(['weekday','local_hour']).estimated_lost_theo_usd
    hm=grouped.sum(min_count=1).unstack('local_hour').reindex(index=weekdays,columns=hours)
    present=grouped.size().unstack('local_hour').reindex(index=weekdays,columns=hours).fillna(0)>0
    hm=hm.where(present,0)  # known no-outage cells are zero; missing estimates stay missing
    labels=[f'{h%12 or 12} {"a.m." if h<12 else "p.m."}' for h in hours]
    heat_fig=figure(height=320,legend=False)
    heat_fig.add_trace(go.Heatmap(z=hm.values,x=labels,y=hm.index,colorscale=SEQ_BLUE,xgap=2,ygap=2,
        hoverongaps=False,colorbar=dict(title=dict(text='Lost expected<br>value ($)'),tickprefix='$',thickness=12),
        hovertemplate='%{y}, %{x}<br>Lost Expected Value: $%{z:,.0f}<extra></extra>'))
    heat_fig.update_layout(xaxis=dict(type='category',dtick=3,tickangle=0),yaxis=dict(autorange='reversed'))
    ht=hm.rename_axis('Weekday').reset_index().melt(id_vars='Weekday',var_name='Local hour',value_name=LOSS)
    ht['Local hour']=ht['Local hour'].map(dict(zip(hours,labels)))
    heat=Chart('downtime-heat','Lost Expected Value by weekday and hour',heat_fig,'Hourly downtime estimates',wide=True,
        subtitle='Darker cells = higher estimated losses. Gaming days run 6 a.m.–6 a.m.; blank cells have unavailable estimates.',
        table=table(ht,{LOSS:fmt_money}))

    monthly=monthly_losses(dh)
    mf=figure(height=320,legend=False)
    names=monthly.month.dt.strftime('%b %Y')
    mf.add_trace(go.Bar(x=monthly.estimated_lost_theo_usd,y=names,orientation='h',marker_color=BLUE,
        text=monthly.estimated_lost_theo_usd.map(fmt_short_money),textposition='outside',cliponaxis=False,
        customdata=monthly[['lost_theo_low_usd','lost_theo_high_usd','downtime_hours','coverage']],
        hovertemplate='%{y}<br>Estimated Lost Expected Value: $%{x:,.0f}<br>Scenario range: $%{customdata[0]:,.0f}–$%{customdata[1]:,.0f}'
            '<br>Recorded downtime: %{customdata[2]:,.1f} machine-hours<br>Downtime with estimates: %{customdata[3]:.1%}<extra></extra>'))
    mf.update_layout(xaxis=dict(title_text='Estimated earnings foregone during downtime ($)',tickprefix='$',rangemode='tozero',showgrid=True,gridcolor=GRID),
        yaxis=dict(autorange='reversed'),margin=dict(r=65))
    mt=monthly.rename(columns={'month':'Month','estimated_lost_theo_usd':LOSS,'lost_theo_low_usd':'Low scenario',
        'lost_theo_high_usd':'High scenario','downtime_hours':'Machine-hours down','estimated_hours':'Hours with loss estimates','coverage':'Estimate coverage'})
    month_chart=Chart('downtime-month','Monthly estimated earnings lost to downtime',mf,'Hourly downtime estimates',
        subtitle='Each bar is the estimated dollar value of earnings foregone that month. Scenario ranges are in the table and hover details; they are not confidence intervals.',
        table=table(mt,{'Month':lambda v:v.strftime('%B'),LOSS:fmt_money,'Low scenario':fmt_money,'High scenario':fmt_money,
            'Machine-hours down':lambda v:fmt_num(v,1),'Hours with loss estimates':lambda v:fmt_num(v,1),'Estimate coverage':fmt_pct}))

    makers=dh.groupby('manufacturer').agg(lost=('estimated_lost_theo_usd',loss_sum),
        low=('lost_theo_low_usd',loss_sum),high=('lost_theo_high_usd',loss_sum),down=('downtime_seconds','sum'),machines=('machine_id','nunique')).reset_index().sort_values('lost')
    makers['hours']=makers.down/3600
    fig3=figure(height=300,legend=False)
    fig3.add_trace(go.Bar(x=makers.lost,y=makers.manufacturer,orientation='h',marker_color=BLUE,
        customdata=makers[['hours','machines']],hovertemplate='%{y}<br>Lost Expected Value: $%{x:,.0f}<br>%{customdata[0]:,.1f} machine-hours down across %{customdata[1]} machines<extra></extra>'))
    fig3.update_layout(xaxis=dict(title_text=LOSS+' ($)',tickprefix='$',showgrid=True,gridcolor=GRID))
    maker_table=makers[['manufacturer','machines','hours','lost','low','high']].copy()
    maker_table.columns=['Manufacturer','Machines','Machine-hours down',LOSS,'Low scenario','High scenario']
    maker_chart=Chart('downtime-mfr','Lost Expected Value by manufacturer',fig3,'Hourly downtime estimates',
        table=table(maker_table,{'Machine-hours down':lambda v:fmt_num(v,1),LOSS:fmt_money,'Low scenario':fmt_money,'High scenario':fmt_money}))

    shifts=faults.groupby('shift').agg(tickets=('operation_id','count'),wait=('response_hours','median'),repair=('repair_hours','median')).reindex(SHIFTS).reset_index()
    shifts['wait']*=60
    shifts['repair']*=60
    shifts['label']=shifts['shift'].map(lambda s:f'{s}<br>{SHIFTS[s]}')
    rf=figure(height=320,barmode='group')
    for col,label,color in [('wait','Median wait to start',BLUE),('repair','Median repair duration',ORANGE)]:
        rf.add_trace(go.Bar(x=shifts.label,y=shifts[col],name=label,marker_color=color,
            hovertemplate='%{x}: %{y:,.0f} minutes<extra>'+label+'</extra>'))
    rf.update_layout(yaxis_title_text='Median minutes per fault ticket')
    st=shifts[['shift','tickets','wait','repair']].copy()
    st['shift']=st['shift'].map(lambda s:f'{s} ({SHIFTS[s]})')
    st['tickets']=st.tickets.fillna(0)
    st.columns=['Local shift','Fault tickets','Median wait to start (min)','Median repair duration (min)']
    response=Chart('downtime-response','Wait time and repair duration by shift',rf,'Fault repair tickets',
        subtitle='Wait: ticket opening to work start. Repair: work start to machine availability. Shift is assigned when the fault ticket opens.',
        table=table(st,{'Fault tickets':fmt_num,'Median wait to start (min)':lambda v:fmt_num(v,0),'Median repair duration (min)':lambda v:fmt_num(v,0)}))

    # Include zero-fault weeks instead of drawing a line across missing weeks.
    weeks=pd.date_range(pd.Timestamp(f.start).to_period('W-SUN').start_time,pd.Timestamp(f.end).to_period('W-SUN').start_time,freq='7D')
    counts=faults.assign(week=pd.to_datetime(faults.gaming_date).dt.to_period('W-SUN').dt.start_time).groupby('week').size().reindex(weeks,fill_value=0)
    full=(weeks>=pd.Timestamp(f.start))&(weeks+pd.Timedelta(days=6)<=pd.Timestamp(f.end))
    counts=counts[full] if full.any() else counts
    wf=figure(height=280,legend=False,hovermode='closest')
    wf.add_trace(go.Scatter(x=counts.index,y=counts.values,mode='lines+markers',line=dict(color=BLUE,width=2),
        hovertemplate='Week of %{x|%b %d}<br>%{y:,.0f} fault tickets<extra></extra>'))
    wf.update_layout(yaxis=dict(title_text='Fault repair tickets',rangemode='tozero',dtick=1 if counts.max()<10 else None))
    week_table=counts.rename('Fault tickets').rename_axis('Week starting').reset_index()
    weekly=Chart('downtime-weekly','Fault repair tickets by week',wf,'Fault repair tickets',wide=True,
        subtitle='Complete weeks.' if full.any() else 'Partial weeks within the selected period.',
        table=table(week_table,{'Week starting':lambda v:v.strftime('%b %d'),'Fault tickets':fmt_num}))

    top=dh.groupby(['machine_id','manufacturer']).agg(down=('downtime_seconds','sum'),lost=('estimated_lost_theo_usd',loss_sum)).reset_index().sort_values('lost',ascending=False).head(15)
    tt=pd.DataFrame({'Machine':top.machine_id,'Manufacturer':top.manufacturer,'Machine-hours down':top.down/3600,
        LOSS:top.lost})
    definitions=Markup('<dl class="indicator-legend"><div><dt>Shifts (casino local time)</dt><dd>Day: 6 a.m.–2 p.m. · Swing: 2–10 p.m. · Grave: 10 p.m.–6 a.m.</dd></div>'
        '<div><dt>Lost Expected Value</dt><dd>Estimated gross earnings foregone during recorded downtime, using matched peer activity. This is a modeled estimate, not observed lost revenue. The scenarios do not establish net floor loss after players switch machines.</dd></div></dl>')
    return dict(headline=headline(f,dh),compact=True,rail=rail,
        sections=[dict(title='Measures and shifts',blocks=[definitions]),
            dict(charts=[heat,month_chart,maker_chart,response,weekly]),
            dict(title='Operation types',intro='Ticket counts, recorded direct costs and median durations. A dash means the duration is unavailable or no tickets were recorded.',
                blocks=[operations_panel(tickets)],source='Recorded maintenance and operation tickets'),
            dict(title='Machines with the largest estimated losses',blocks=[table(tt,{'Machine-hours down':lambda v:fmt_num(v,1),
                LOSS:fmt_money},{'Machine':lambda r:f'/machines/{r.Machine}{f.qs()}'})],source='Hourly downtime estimates')],
        scope_note='Unavailable loss estimates remain missing, not zero. Scenario totals cover estimable downtime only.')
