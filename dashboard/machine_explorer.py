"""Machine exploration using observed earnings and overlapping indicators."""

from dataclasses import replace
from datetime import timedelta, timezone
import html
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

from .charts import AXIS, BLUE, GRID, MUTED, ORANGE, SEQ_BLUE, SURFACE, Chart, figure, fmt_money, fmt_num, fmt_pct, table
from .contract import EVENT_TYPES, UNDERPERFORMANCE_INDICATORS
from .data import T, Filters, query
from .machine_summary import summarize


def load_days(f, machine_id=None):
    scope,params=f.where(alias='d')
    if machine_id:
        scope+=' AND d.machine_id=?'
        params.append(machine_id)
    return query(f'''WITH pools AS (
        SELECT *, count(*) FILTER(WHERE available_seconds>0) OVER z AS peer_n,
            sum(available_seconds) OVER z/3600.0 AS zone_hours,
            sum(house_win_usd) FILTER(WHERE available_seconds>0) OVER z AS zone_income,
            sum(actual_contribution_usd) FILTER(WHERE available_seconds>0) OVER z AS zone_contribution,
            sum(coin_in_usd) FILTER(WHERE available_seconds>0) OVER z AS zone_wagers
        FROM {T('mart_machine_daily')} WHERE gaming_date BETWEEN ? AND ?
        WINDOW z AS (PARTITION BY zone_id,gaming_date)
        ) SELECT d.machine_id,d.gaming_date,d.month_start,d.zone_id,d.zone_name,d.bank_id,
            d.location_id,d.config_id,d.x_m,d.y_m,d.manufacturer,d.theme,
            d.available_seconds/3600.0 AS hours,d.available_seconds,d.scheduled_seconds,d.calendar_day_seconds,
            d.house_win_usd::DOUBLE AS income,d.actual_contribution_usd::DOUBLE AS contribution,
            d.coin_in_usd::DOUBLE AS wagers,d.machine_cost_usd::DOUBLE AS costs,
            d.theo_usd::DOUBLE AS theoretical,
            CASE WHEN peer_n-1>=3 AND available_seconds>0 THEN
              (zone_income-house_win_usd)/nullif(zone_hours-available_seconds/3600.0,0) END AS peer_income_rate,
            CASE WHEN peer_n-1>=3 AND available_seconds>0 THEN
              (zone_contribution-actual_contribution_usd)/nullif(zone_hours-available_seconds/3600.0,0) END AS peer_contribution_rate,
            CASE WHEN peer_n-1>=3 AND available_seconds>0 THEN
              (zone_wagers-coin_in_usd)/nullif(zone_hours-available_seconds/3600.0,0) END AS peer_wager_rate
        FROM pools d WHERE {scope} ORDER BY d.machine_id,d.gaming_date''', [f.start,f.end]+params)


def repair_comparisons(daily,f):
    tickets=query(f'''SELECT operation_id,machine_id,gaming_date,available_at_utc,comparison_status,
        response_hours,repair_hours,event_type FROM {T('mart_tickets')}
        WHERE event_type='fault_repair' AND gaming_date BETWEEN ? AND ?
        ORDER BY gaming_date''',[f.start,f.end])
    comparisons=[]
    groups={mid:g for mid,g in daily.groupby('machine_id')}
    for ticket in tickets.itertuples():
        if ticket.machine_id not in groups or pd.isna(ticket.available_at_utc) or ticket.comparison_status!='comparable':
            continue
        days=groups[ticket.machine_id]
        # Convert the repair timestamp to this casino's 06:00 gaming-day boundary.
        completed=pd.Timestamp(ticket.available_at_utc).to_pydatetime().replace(tzinfo=timezone.utc)
        repaired=(completed.astimezone(ZoneInfo('America/Los_Angeles'))-timedelta(hours=6)).date()
        complete=days[(days.scheduled_seconds==days.calendar_day_seconds)&(days.hours>0)]
        before=complete[complete.gaming_date.dt.date<ticket.gaming_date.date()].tail(7)
        after=complete[complete.gaming_date.dt.date>repaired].head(7)
        if len(before)!=7 or len(after)!=7:
            continue
        combined=pd.concat([before,after])
        if combined.location_id.nunique()!=1 or combined.config_id.nunique()!=1:
            continue
        before_rate=before.income.sum()/before.hours.sum()
        after_rate=after.income.sum()/after.hours.sum()
        change=after_rate-before_rate
        relative=change/abs(before_rate) if before_rate else None
        comparisons.append(dict(machine_id=ticket.machine_id,ticket=ticket.operation_id,
            before=before_rate,after=after_rate,change=change,relative=relative,
            flagged=relative is not None and abs(relative)>=.20))
    return pd.DataFrame(comparisons,columns=['machine_id','ticket','before','after','change','relative','flagged'])


def add_indicators(machines):
    m=machines.copy()
    # Indicators annotate observed underperformers; data quality is a separate notice.
    m['low_earnings']=(m.income_gap<0)&(m.peer_coverage>=.8)&(m.covered_day>=14)
    m['low_demand']=m.low_earnings&(m.wager_ratio<.8)
    m['persistent']=m.low_earnings&(m.measured>=3)&(m.below>=3)&(m.below/m.measured.replace(0,float('nan'))>=2/3)
    m['low_availability']=m.low_earnings&(m.availability<.95)
    m['repair_change']=m.low_earnings&(m.repair_changes>0)
    m['indicator_labels']=m.apply(lambda r:', '.join(label for key,label,_ in UNDERPERFORMANCE_INDICATORS if r[key]),axis=1)
    m['data_notice']=m.apply(lambda r:'; '.join(s for s in [
        f'{int(r.days)} active days' if r.days<60 else '',
        'Limited peer coverage' if pd.isna(r.peer_coverage) or r.peer_coverage<.8 or r.covered_day<14 else ''] if s),axis=1)
    return m


def machine_data(f,machine_id=None):
    days=load_days(f,machine_id)
    if days.empty:
        return days,pd.DataFrame(),pd.DataFrame(),pd.DataFrame()
    machines,monthly=summarize(days)
    repairs=repair_comparisons(days,f)
    changes=repairs[repairs.flagged].groupby('machine_id').size() if not repairs.empty else pd.Series(dtype=int)
    machines['repair_changes']=machines.machine_id.map(changes).fillna(0).astype(int)
    latest=days.sort_values('gaming_date').drop_duplicates('machine_id',keep='last')
    machines=machines.merge(latest[['machine_id','x_m','y_m','location_id','manufacturer','theme','gaming_date']],on='machine_id')
    machines=machines.merge(days.groupby('machine_id').theoretical.sum().rename('theoretical'),on='machine_id')
    return days,add_indicators(machines),monthly,repairs


def rail(m):
    hours=m.hours.sum()
    scheduled=m.scheduled_seconds.sum()
    return [dict(label='Machines',value=fmt_num(len(m)),sub='In the current selection'),
        dict(label='Actual house win',value=fmt_money(m.income.sum()),sub='Wagers minus payouts'),
        dict(label='Actual house win / hr',value=fmt_money(m.income.sum()/hours if hours else None,2),sub='Per available operating hour'),
        dict(label='Actual contribution',value=fmt_money(m.contribution.sum()),sub='After supplied machine costs'),
        dict(label='Availability',value=fmt_pct(m.available_seconds.sum()/scheduled if scheduled else None),sub='Available ÷ scheduled time')]


def observed_table(m,f):
    shown=m.sort_values(['income','machine_id'])[[
        'machine_id','zone_name','bank_id','manufacturer','theme','days','wagers','income','income_rate',
        'contribution','contribution_rate','income_gap','availability','indicator_labels','data_notice']].copy()
    shown.columns=['Machine','Zone','Bank','Manufacturer','Game','Active days','Wagered','Actual house win',
        'Actual house win / hr','Actual contribution','Actual contribution / hr','Earnings gap / hr',
        'Availability','Underperformance indicators','Data notes']
    formats={c:fmt_money for c in ['Wagered','Actual house win','Actual contribution']}
    formats.update({c:lambda v:fmt_money(v,2) for c in ['Actual house win / hr','Actual contribution / hr','Earnings gap / hr']})
    formats['Availability']=fmt_pct
    return table(shown,formats,{'Machine':lambda r:f'/machines/{r.Machine}{f.qs()}'})


def floor_map(m,f):
    # A floor snapshot avoids drawing retired and replacement cabinets on one slot.
    end=query(f'SELECT max(gaming_date) d FROM {T("mart_machine_daily")} WHERE gaming_date BETWEEN ? AND ?',[f.start,f.end]).iloc[0,0]
    positioned=m[(m.gaming_date==end)&m.x_m.notna()&m.y_m.notna()]
    fig=figure(height=570,legend=False)
    for zone,g in positioned.groupby('zone_name'):
        x0,x1=g.x_m.min()-2,g.x_m.max()+2
        y0,y1=g.y_m.min()-3,g.y_m.max()+3
        fig.add_shape(type='rect',x0=x0,x1=x1,y0=y0,y1=y1,line=dict(color=AXIS,width=1),fillcolor='rgba(138,133,124,0.04)',layer='below')
        fig.add_annotation(x=(x0+x1)/2,y=y1+1.5,text=html.escape(zone),showarrow=False,font=dict(size=12,color=MUTED))
    custom=[[r.machine_id,f'/machines/{r.machine_id}{f.qs()}',html.escape(r.zone_name),r.bank_id,
             r.income,r.income_rate,fmt_pct(r.availability),html.escape(r.indicator_labels or '—')]
            for r in positioned.itertuples()]
    fig.add_trace(go.Scatter(x=positioned.x_m,y=positioned.y_m,mode='markers',customdata=custom,
        marker=dict(size=13 if f.bank else 10,symbol=['square' if v else 'circle' for v in positioned.low_earnings],
            color=positioned.income_rate,colorscale=SEQ_BLUE,showscale=True,
            colorbar=dict(title=dict(text='Actual win<br>$/hr')),
            line=dict(color=[ORANGE if v else SURFACE for v in positioned.low_earnings],width=1.5)),
        hovertemplate='<b>%{customdata[0]}</b> · %{customdata[2]} · %{customdata[3]}<br>'
            'Actual house win: $%{customdata[4]:,.0f}<br>Actual win/hour: $%{customdata[5]:,.2f}<br>'
            'Availability: %{customdata[6]}<br>%{customdata[7]}<br>Click for machine details<extra></extra>'))
    fig.update_layout(xaxis=dict(title_text='Floor position (metres)',showgrid=False,zeroline=False),
        yaxis=dict(title_text='',scaleanchor='x',scaleratio=1,showgrid=False,zeroline=False),clickmode='event',dragmode='pan')
    missing=len(m[m.gaming_date==end])-len(positioned)
    note=f'{len(positioned)} mapped machines. '+(f'{missing} have no coordinates. ' if missing else '')
    return Chart('explorer-map','Casino floor · click a machine',fig,'Recorded machine positions and earnings',
        subtitle=note+'Positions at the end of the selected period; colour shows actual win/hour over that period. Orange squares: below-peer earnings. Zone boxes are approximate.',
        wide=True,extra={'click_href_index':1})


def peer_chart(m):
    d=m[m.income_gap.notna()]
    fig=figure(height=380)
    if not d.empty:
        lo=min(d.peer_income_rate.min(),d.matched_income_rate.min(),0)
        hi=max(d.peer_income_rate.max(),d.matched_income_rate.max(),1)
        fig.add_trace(go.Scatter(x=[lo,hi],y=[lo,hi],mode='lines',name='Equal earnings',line=dict(color=AXIS,dash='dash'),hoverinfo='skip'))
    for label,color,mask in [('Below peers',ORANGE,d.income_gap<0),('At or above peers',BLUE,d.income_gap>=0)]:
        g=d[mask]
        fig.add_trace(go.Scatter(x=g.peer_income_rate,y=g.matched_income_rate,mode='markers',name=label,
            customdata=g.machine_id,marker=dict(color=color,size=8),
            hovertemplate='%{customdata}<br>Observed zone peers: $%{x:,.2f}/hr<br>Machine: $%{y:,.2f}/hr<extra></extra>'))
    fig.update_layout(xaxis=dict(title_text='Observed zone-peer house win / hr',tickprefix='$'),
        yaxis=dict(title_text='Machine actual house win / hr',tickprefix='$'))
    return Chart('explorer-peers','Actual earnings vs. observed peers',fig,'Same-date machine earnings',
        subtitle='Each dot is a machine. Below the dashed line = lower actual earnings. Matching dates and target available hours; at least 3 zone peers.')


def zone_chart(days,m,f):
    data=days[days.machine_id.isin(m.machine_id)]
    group='bank_id' if f.zone else 'zone_name'
    totals=data.groupby(group)[['income','hours']].sum()
    totals['rate']=totals.income/totals.hours.replace(0,float('nan'))
    totals=totals.sort_values('rate')
    fig=figure(height=380,legend=False)
    fig.add_trace(go.Bar(x=totals.rate,y=totals.index,orientation='h',marker_color=BLUE,
        hovertemplate='%{y}: $%{x:,.2f}/hr<extra>Actual house win</extra>'))
    fig.update_layout(xaxis=dict(title_text='Actual house win per available hour',tickprefix='$',showgrid=True,gridcolor=GRID))
    return Chart('explorer-zones',f"Actual house win per hour · {'banks' if f.zone else 'zones'}",fig,'Machine earnings records',
        subtitle='Total observed house win divided by total available hours.')


def build(f):
    days,m,monthly,repairs=machine_data(f)
    page=dict(title_override='Machine Explorer',compact=True,headline='',indicator_filter=True,
        indicator_options=UNDERPERFORMANCE_INDICATORS,sections=[],
        scope_note='House win = wagers − payouts. Contribution subtracts supplied machine costs. '
        'Peer comparisons are descriptive and can reflect game mix and payout variation. Indicators follow the selected period; none proves replacement value.')
    if m.empty:
        page['sections']=[dict(title='No machines in this selection',blocks=[Markup('<p class="empty">Choose another bank or period.</p>')])]
        return page
    if f.indicator:
        m=m[m[f.indicator]].copy()
    if m.empty:
        page['sections']=[dict(title='No machines match this indicator',blocks=[Markup('<p class="empty">Choose “All machines” to see the full selection.</p>')])]
        return page
    page['rail']=rail(m)
    legend='<dl class="indicator-legend">'+''.join(f'<div><dt>{html.escape(label)}</dt><dd>{html.escape(description)}</dd></div>' for _,label,description in UNDERPERFORMANCE_INDICATORS)+'</dl>'
    page['sections']=[dict(charts=[floor_map(m,f),peer_chart(m),zone_chart(days,m,f)]),
        dict(title='Underperformance indicators',blocks=[Markup(legend)],source='Observed machine and repair records'),
        dict(title='Every machine',intro='Sorted by total actual house win, lowest first. Click a machine to inspect its earnings, placements and repairs.',
            blocks=[observed_table(m,f)],source='Machine earnings and operating costs')]
    theoretical=m[['machine_id','theoretical']].rename(columns={'machine_id':'Machine','theoretical':'Theoretical house win (estimate)'})
    page['sections'][-1]['blocks'].append(Markup('<details class="selection-method"><summary>Optional modeled reference</summary><p>Theoretical house win is an estimate from wagers and configured RTP. It is not observed income and does not determine these indicators or the table order.</p>')+
        table(theoretical,{'Theoretical house win (estimate)':fmt_money})+Markup('</details>'))
    return page


def detail(f,machine_id):
    # Machine histories follow the selected dates across moves; location and
    # indicator filters are retained only for the link back to the Explorer.
    own=replace(f,zone='',bank='',indicator='')
    days,m,monthly,repairs=machine_data(own,machine_id)
    if m.empty:
        exists=query(f'SELECT machine_id FROM {T("mart_machine_daily")} WHERE machine_id=? LIMIT 1',[machine_id])
        if exists.empty:
            return None
        return dict(title_override=f'Machine {machine_id}',back=True,location_filters=False,compact=True,headline='',
            sections=[dict(title='No activity in the selected period',intro='Choose a wider date range.')])
    r=m.iloc[0]
    daily=days.sort_values('gaming_date')
    fig=figure(height=330,hovermode='x unified')
    fig.add_trace(go.Scatter(x=daily.gaming_date,y=daily.income,name='Actual house win',mode='lines',line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=daily.gaming_date,y=daily.contribution,name='Actual contribution',mode='lines',line=dict(color=ORANGE)))
    fig.update_layout(yaxis=dict(title_text='Observed dollars per gaming day',tickprefix='$'))
    actual=Chart('machine-actual-history','Daily actual earnings and contribution',fig,'Daily machine earnings',wide=True)
    fig2=figure(height=280,legend=False)
    fig2.add_trace(go.Bar(x=daily.gaming_date,y=daily.available_seconds/daily.scheduled_seconds.replace(0,float('nan')),
        marker_color=BLUE,hovertemplate='%{x|%b %d}: %{y:.1%}<extra>Availability</extra>'))
    fig2.update_layout(yaxis=dict(title_text='Availability',tickformat='.0%',range=[0,1.02]))
    availability=Chart('machine-actual-availability','Daily availability',fig2,'Machine operating records',wide=True)
    runs=daily.assign(run=((daily.location_id!=daily.location_id.shift())|(daily.config_id!=daily.config_id.shift())).cumsum()).groupby('run').agg(
        Slot=('location_id','first'),Zone=('zone_name','first'),Bank=('bank_id','first'),Game=('theme','first'),From=('gaming_date','min'),To=('gaming_date','max'))
    history=table(runs,{'From':lambda v:v.strftime('%b %d'),'To':lambda v:v.strftime('%b %d')},sortable=False)
    ticket_rows=query(f'''SELECT operation_id,event_type,gaming_date,response_hours,repair_hours
        FROM {T('mart_tickets')} WHERE machine_id=? AND gaming_date BETWEEN ? AND ? ORDER BY gaming_date''',[machine_id,f.start,f.end])
    ticket_rows['event_type']=ticket_rows.event_type.map(lambda e:EVENT_TYPES.get(e,str(e).replace('_',' ')))
    ticket_rows.columns=['Ticket','Type','Gaming date','Response hours','Repair hours']
    sections=[dict(charts=[actual,availability]),dict(title='Observed performance',blocks=[observed_table(m,own)]),
        dict(title='Placement history',blocks=[history],source='Recorded daily machine placements'),
        dict(title='Service tickets',blocks=[table(ticket_rows,{'Response hours':lambda v:fmt_num(v,1),'Repair hours':lambda v:fmt_num(v,1)}) if not ticket_rows.empty else Markup('<p class="empty">No service tickets in this period.</p>')])]
    if not repairs.empty:
        rt=repairs[['ticket','before','after','change','relative']].copy()
        rt.columns=['Ticket','Actual win / hr before','Actual win / hr after','Change / hr','Relative change']
        sections.append(dict(title='Actual earnings around repairs',intro='Seven complete active dates before and after each comparable repair, within the selected period. Associations do not establish that the repair caused a change.',
            blocks=[table(rt,{'Actual win / hr before':lambda v:fmt_money(v,2),'Actual win / hr after':lambda v:fmt_money(v,2),'Change / hr':lambda v:fmt_money(v,2),'Relative change':fmt_pct})]))
    reference=pd.DataFrame({'Machine':[machine_id],'Theoretical house win (estimate)':[r.theoretical]})
    sections.append(dict(title='Optional modeled reference',blocks=[Markup('<details class="selection-method"><summary>Theoretical house win and payout uncertainty</summary><p>This is an estimate from configured RTP and observed wagers, not actual earnings. A difference from actual results does not identify luck, a fault or wrongdoing. Observed payouts can vary substantially, especially with limited exposure or high-volatility games.</p>')+table(reference,{'Theoretical house win (estimate)':fmt_money})+Markup('</details>')]))
    return dict(title_override=f'Machine {machine_id}',back=True,location_filters=False,compact=True,headline='',
        lede=f'{r.zone_name} · {r.bank_id} · {r.manufacturer} · {r.theme}',rail=rail(m),sections=sections,
        scope_note='All measures follow the selected dates. Placement labels use the last observed position in that period. '+
            ('Indicators: '+r.indicator_labels+'. ' if r.indicator_labels else '')+(r.data_notice or ''))
