"""Observed machine economics and same-date neighbour comparisons."""

import pandas as pd
import plotly.graph_objects as go
import duckdb
from functools import lru_cache
from markupsafe import Markup

from .charts import AXIS, BLUE, GRID, MUTED, ORANGE, Chart, figure, fmt_money, fmt_num, fmt_pct, table
from .data import T, Filters, query, DB_PATH, SCHEMA, _db_stamp


@lru_cache(maxsize=4)
def selection_audit(stamp, database):
    """Recompute the audited cohort from this database, never a stale CSV."""
    from casino_pipeline.analysis.replacements import audit
    with duckdb.connect(database,read_only=True) as con:
        result=audit(con)
    return result


def audited_selection(machines, f):
    result=selection_audit(_db_stamp(),str(DB_PATH)) if SCHEMA=='marts' else None
    if result is None:
        raise ValueError('The replacement audit currently requires the published marts schema.')
    selected=pd.DataFrame(result['selected'])
    if selected.empty:
        selected=pd.DataFrame(columns=['machine_id','replacement_rank'])
    all_evidence=pd.DataFrame(result['rows'])
    # Location drilldowns retain all bank machines. They are comparisons, not
    # fabricated new members of the fixed full-window replacement shortlist.
    if f.zone or f.bank:
        shortlist=machines[machines.hours>0].head(10).copy()
        title=f'Local comparison · {len(shortlist)} machines'
    else:
        shortlist=machines.merge(selected[['machine_id','replacement_rank']],on='machine_id',how='inner')
        shortlist=shortlist.sort_values('replacement_rank').copy()
        shortlist['rank']=shortlist.replacement_rank
        title=f'Replacement shortlist · {len(shortlist)} machines'
    shortlist=shortlist.merge(all_evidence,on='machine_id',suffixes=('','_audit'),how='left')
    selected_ranks={r['machine_id']:r['replacement_rank'] for r in result['selected']}
    shortlist['audit_status']=shortlist.machine_id.map(lambda mid:f"Candidate #{selected_ranks[mid]}" if mid in selected_ranks else 'Not shortlisted')
    return shortlist,result,title


def factor_sections(shortlist,result):
    """Expose gates, competing explanations and modeled economics separately."""
    def status(value):
        return 'Unavailable' if pd.isna(value) else ('Flagged' if value else 'Not flagged')
    rows=[]
    for r in shortlist.itertuples():
        rows.append({
            'Machine':r.machine_id,'Audit status':r.audit_status,
            'Exposure':f'{r.active_days} active / {r.positive_wager_days} wager days',
            'Peer date coverage':r.peer_coverage_fraction,
            'Wagering vs. zone peers':r.peer_coin_in_rate_ratio,
            'Weak months':f'{r.persistent_months}/{r.eligible_months}',
            'Weak in June':'Yes' if r.weak_in_final_month else 'No',
            'Availability (Jan–Jun)':r.availability_ratio,
            'Location flag':status(r.location_flag),'Downtime flag':status(r.downtime_flag),
            'Repair recovery':status(r.repair_rebound_flag),
            'Payout anomaly':status(r.hold_anomaly_flag),
            'Residual dependence':status(r.dependence_warning),
            'Concentrated exposure':status(r.exposure_concentration_warning),
            'Statistical disagreement':status(r.method_disagreement),
        })
    factors=pd.DataFrame(rows)
    matched=pd.DataFrame([{
        'Machine':r.machine_id,
        'Wagering vs. zone peers':r.peer_coin_in_rate_ratio,
        'Wagering vs. comparable games':r.matched_coin_ratio,
        'Modeled earnings vs. zone peers':r.peer_rate_ratio,
        'Comparable-game days':r.matched_days,
        'Machine costs / hr (selected dates)':r.costs/r.hours if r.hours else None,
        'Actual contribution / hr (selected dates)':r.contribution_rate,
        'Modeled contribution / hr (rank input)':float(r.expected_contribution_per_available_hour),
        'Repair evidence':r.repair_evidence_status.replace('_',' '),
    } for r in shortlist.itertuples()])
    economics=[]
    selected_lookup={r['machine_id']:r for r in result['selected']}
    for mid in shortlist.machine_id:
        r=selected_lookup.get(mid)
        if r:
            economics.append({'Machine':mid,'July lease cost':r['lease_cash_cost_usd'],
                'Break-even modeled uplift / hr':r['break_even_theo_uplift_per_hour'],
                'July net: 50% gap recovery':r['lease_net_50pct_gap_usd'],
                'July net: 100% gap recovery':r['lease_net_100pct_gap_usd']})
    sections=[dict(title='Selection factors · January–June 2025',
        intro='Fixed audit evidence. Period filters change observed earnings, not shortlist membership.',
        blocks=[table(factors,{'Peer date coverage':fmt_pct,'Wagering vs. zone peers':fmt_pct,'Availability (Jan–Jun)':fmt_pct})],
        source='Machine activity, operating records and payout analysis'),
        dict(title='Game mix and ranking inputs',
        intro='Comparable games share RTP and volatility within the same zone and dates. Modeled contribution is an estimate, separate from actual earnings.',
        blocks=[table(matched,{'Wagering vs. zone peers':fmt_pct,'Wagering vs. comparable games':fmt_pct,
            'Modeled earnings vs. zone peers':fmt_pct,'Machine costs / hr (selected dates)':lambda v:fmt_money(v,2),
            'Actual contribution / hr (selected dates)':lambda v:fmt_money(v,2),'Modeled contribution / hr (rank input)':lambda v:fmt_money(v,2)}),
            Markup('<details class="selection-method"><summary>Selection rules and limitations</summary>'
                '<p>Eligible machines are active June 30, with at least 60 active and 30 wagering dates and 80% peer-date coverage. '
                'Wagering and modeled expected earnings must each be more than 20% below zone peers, in at least four eligible months including June. '
                'Months require 21 peer-covered and 14 wagering dates. Positive location, downtime, repair recovery, payout anomaly, dependence, '
                'concentrated-exposure or statistical-disagreement flags exclude a machine. Unavailable repair comparisons remain disclosed. '
                'Candidates are ordered by modeled contribution per available hour; this ranking is not an observed earnings ranking. '
                'A 20% peer-gap threshold is an analytical choice: requiring five weak months leaves eight candidates; '
                'a 30% gap leaves none. Payout tests assess variation, not replacement value. '
                'Close performance against comparable games weakens a cabinet-specific explanation.</p></details>')],
        source='Machine costs, peer comparisons and game settings')]
    if economics:
        econ=pd.DataFrame(economics)
        sections.append(dict(title='Replacement economics · July scenarios',
            intro='Assumed recovery of the modeled zone-peer earnings gap; not measured replacement effects. Includes lead time, installation downtime and lease charges. Other ongoing costs remain unchanged; existing lease costs are not credited as savings.',
            blocks=[table(econ,{col:(lambda v:fmt_money(v)) for col in econ.columns if col!='Machine'})],
            source='Replacement catalogue and explicit benefit assumptions'))
    return sections


def observations(f: Filters) -> pd.DataFrame:
    """Compute peers before narrowing targets, so bank filters retain context.

    Peer income is observed house win, not theoretical/expected income. Peer
    rates weight each date by the target's available hours, excluding the target.
    """
    scope, params = f.where(alias='d')
    return query(f"""
        WITH pools AS (
          SELECT *, count(*) FILTER (WHERE available_seconds>0) OVER z AS pool_count,
            sum(available_seconds) OVER z / 3600.0 AS pool_hours,
            sum(house_win_usd) FILTER (WHERE available_seconds>0) OVER z AS pool_income,
            sum(actual_contribution_usd) FILTER (WHERE available_seconds>0) OVER z AS pool_contribution,
            sum(coin_in_usd) FILTER (WHERE available_seconds>0) OVER z AS pool_wagers
          FROM {T('mart_machine_daily')}
          WHERE gaming_date BETWEEN ? AND ?
          WINDOW z AS (PARTITION BY gaming_date,zone_id)
        ), current_scope AS (
          SELECT machine_id FROM {T('mart_machine_daily')}
          WHERE gaming_date=(SELECT max(gaming_date) FROM {T('mart_machine_daily')}
                                WHERE gaming_date BETWEEN ? AND ?)
          {"AND zone_id=?" if f.zone else ""} {"AND bank_id=?" if f.bank else ""}
        )
        SELECT d.machine_id,d.gaming_date,d.month_start,d.zone_name,d.bank_id,
          d.available_seconds/3600.0 AS hours,d.scheduled_seconds,d.available_seconds,
          d.house_win_usd::DOUBLE AS income,d.actual_contribution_usd::DOUBLE AS contribution,
          d.coin_in_usd::DOUBLE AS wagers,d.machine_cost_usd::DOUBLE AS costs,
          CASE WHEN pool_count-1>=3 AND d.available_seconds>0 THEN
            (pool_income-d.house_win_usd)/nullif(pool_hours-d.available_seconds/3600.0,0) END AS peer_income_rate,
          CASE WHEN pool_count-1>=3 AND d.available_seconds>0 THEN
            (pool_contribution-d.actual_contribution_usd)/nullif(pool_hours-d.available_seconds/3600.0,0) END AS peer_contribution_rate,
          CASE WHEN pool_count-1>=3 AND d.available_seconds>0 THEN
            (pool_wagers-d.coin_in_usd)/nullif(pool_hours-d.available_seconds/3600.0,0) END AS peer_wager_rate
        FROM pools d JOIN current_scope c USING(machine_id)
        WHERE {scope} ORDER BY d.machine_id,d.gaming_date
    """, [f.start,f.end,f.start,f.end] + ([f.zone] if f.zone else []) + ([f.bank] if f.bank else []) + params)


def summarize(daily: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Ratios of sums; compare on covered dates, never treat missing peers as zero."""
    data = daily.copy()
    covered = data.peer_income_rate.notna() & (data.hours>0)
    data['covered_hours'] = data.hours.where(covered,0)
    data['covered_income'] = data.income.where(covered,0)
    data['covered_wagers'] = data.wagers.where(covered,0)
    data['covered_contribution'] = data.contribution.where(covered,0)
    data['peer_income'] = (data.peer_income_rate*data.hours).where(covered,0)
    data['peer_contribution'] = (data.peer_contribution_rate*data.hours).where(covered,0)
    data['peer_wagers'] = (data.peer_wager_rate*data.hours).where(covered,0)
    data['covered_day'] = covered.astype(int)
    totals = ['hours','scheduled_seconds','available_seconds','income','contribution','wagers','costs',
              'covered_hours','covered_income','covered_contribution','covered_wagers',
              'peer_income','peer_contribution','peer_wagers','covered_day']
    def aggregate(keys):
        grouped = data.groupby(keys,sort=False)
        result = grouped[totals].sum().reset_index()
        result['days'] = grouped.size().values
        hours = result.hours.replace(0,float('nan'))
        matched_hours = result.covered_hours.replace(0,float('nan'))
        result['income_rate'] = result.income/hours
        result['contribution_rate'] = result.contribution/hours
        result['peer_income_rate'] = result.peer_income/matched_hours
        result['matched_income_rate'] = result.covered_income/matched_hours
        result['peer_contribution_rate'] = result.peer_contribution/matched_hours
        result['income_gap'] = (result.covered_income-result.peer_income)/matched_hours
        result['contribution_gap'] = (result.covered_contribution-result.peer_contribution)/matched_hours
        result['availability'] = result.available_seconds/result.scheduled_seconds.replace(0,float('nan'))
        result['peer_coverage'] = result.covered_hours/hours
        result['wager_ratio'] = result.covered_wagers/result.peer_wagers.replace(0,float('nan'))
        return result
    machines = aggregate(['machine_id'])
    monthly = aggregate(['machine_id','month_start'])
    monthly['measured'] = monthly.covered_day>=7
    monthly['below'] = monthly.measured & (monthly.income_gap<0)
    persistence = monthly.groupby('machine_id')[['measured','below']].sum()
    machines = machines.merge(persistence,on='machine_id',how='left')
    labels = data.sort_values('gaming_date').groupby('machine_id')[['zone_name','bank_id']].last()
    machines = machines.merge(labels,on='machine_id',how='left')
    machines = machines.sort_values(['contribution_rate','machine_id'],na_position='last').reset_index(drop=True)
    machines['rank'] = machines.index+1
    return machines,monthly


def evidence(row):
    facts = []
    if pd.notna(row.income_gap):
        facts.append(f"Earnings {fmt_money(abs(row.income_gap),2)}/hr {'below' if row.income_gap<0 else 'above'} zone peers")
    else:
        facts.append('Peer comparison unavailable')
    if row.measured:
        facts.append(f"below peers in {int(row.below)}/{int(row.measured)} measured months")
    if pd.notna(row.wager_ratio) and row.wager_ratio<1:
        facts.append(f"wagering {1-row.wager_ratio:.0%} below peers")
    if row.availability<0.95:
        facts.append(f"{1-row.availability:.1%} unavailable")
    if row.days<60:
        facts.append(f"{int(row.days)} active days")
    return '; '.join(facts)


def build(f: Filters) -> dict:
    daily = observations(f)
    page = dict(title_override='Machine Summary',compact=True,headline='',
        scope_note='Earnings = wagers − payouts. Contribution = earnings − supplied machine costs. '
        'Peers are other machines in the same zone on the same dates (at least 3); comparisons exclude the target. '
        'Observed results include payout variation and do not estimate replacement returns.',
        sections=[])
    if daily.empty:
        page['sections']=[dict(title='No machines in this selection',
            blocks=[Markup('<p class="empty">Choose another bank or analysis period.</p>')])]
        return page
    machines,monthly = summarize(daily)
    shortlist,audit_result,selection_title = audited_selection(machines,f)
    if shortlist.empty:
        page['sections']=[dict(title='No shortlisted machines with operating hours in this selection',
            intro='Choose a wider period or use a zone or bank filter to inspect local machines.')]
        return page
    # Human-readable names are used in all visible tables and chart tooltips.
    displayed = shortlist.assign(reason=shortlist.apply(evidence,axis=1))[[
        'rank','machine_id','audit_status','zone_name','bank_id','income_rate','contribution_rate',
        'income_gap','availability','days','reason']]
    displayed.columns=['Rank','Machine','Audit status','Zone','Bank','Actual earnings / hr','Actual contribution / hr',
                       'Earnings gap / hr','Availability','Active days','Observed evidence']
    formats={k:lambda v:fmt_money(v,2) for k in ['Actual earnings / hr','Actual contribution / hr','Earnings gap / hr']}
    formats['Availability']=fmt_pct
    page['rail']=[
        dict(label='Audit candidates shown',value=str(int(shortlist.audit_status.str.startswith('Candidate').sum())),sub=f"{len(audit_result['selected'])} in the full-period shortlist"),
        dict(label='Machines in selection',value=fmt_num(len(machines)),sub='Active at the end of the period'),
        dict(label='Actual earnings',value=fmt_money(machines.income.sum()),sub='Wagers minus payouts'),
        dict(label='Actual contribution / hr',value=fmt_money(machines.contribution.sum()/machines.hours.sum() if machines.hours.sum() else None,2),sub='After supplied machine costs'),
        dict(label='Machines earning below peers',value=str(int((machines.income_gap<0).sum())),sub=f'{int(machines.income_gap.notna().sum())} have peer comparisons'),
        dict(label='Availability',value=fmt_pct(machines.available_seconds.sum()/machines.scheduled_seconds.sum() if machines.scheduled_seconds.sum() else None),sub='Available time ÷ scheduled time'),
    ]
    page['sections']=[dict(title=selection_title,
        intro=('Local machines ranked by actual contribution; audit status identifies members of the fixed shortlist.' if f.zone or f.bank else
               'Full-factor audit shortlist; candidate order uses modeled contribution. Actual earnings and contribution are shown separately.'),
        blocks=[table(displayed,formats,{'Machine':lambda r:f'/machines/{r.Machine}{f.qs()}'})],
        source='Machine earnings and operating costs')]
    if shortlist.empty:
        page['sections'].append(dict(title='No available operating hours',
            intro='The selected machines have no available time in this period.'))
        return page
    ordered = shortlist.iloc[::-1]
    comparison=figure(height=max(330,45*len(shortlist)),legend=True)
    comparison.add_trace(go.Bar(y=ordered.machine_id,x=ordered.matched_income_rate,name='Machine earnings',orientation='h',
        marker_color=ORANGE,hovertemplate='%{y}: $%{x:,.2f}/hr<extra>Actual earnings</extra>'))
    comparison.add_trace(go.Bar(y=ordered.machine_id,x=ordered.peer_income_rate,name='Zone peer earnings',orientation='h',
        marker_color=BLUE,hovertemplate='%{y}: $%{x:,.2f}/hr<extra>Observed zone peers</extra>'))
    comparison.update_layout(barmode='group',xaxis=dict(title_text='Actual earnings per available hour ($)',
        tickprefix='$',showgrid=True,gridcolor=GRID),yaxis=dict(type='category',categoryorder='array',categoryarray=list(ordered.machine_id)))
    compare_table=shortlist[['machine_id','matched_income_rate','peer_income_rate','income_gap','peer_coverage']].copy()
    compare_table.columns=['Machine','Actual earnings / hr','Zone peer earnings / hr','Earnings gap / hr','Peer coverage']
    compare_formats={k:lambda v:fmt_money(v,2) for k in list(compare_table.columns)[1:4]}
    compare_formats['Peer coverage']=fmt_pct
    bar=Chart('machine-earnings','Actual earnings vs. zone peers',comparison,'Machine earnings records',
        subtitle='Wagers minus payouts per available hour. Both series use only dates with peer coverage.',
        table=table(compare_table,compare_formats))
    selected_months=monthly[monthly.machine_id.isin(shortlist.machine_id)].copy()
    selected_months.loc[~selected_months.measured,'income_gap']=float('nan')
    pivot=selected_months.pivot(index='machine_id',columns='month_start',values='income_gap').reindex(ordered.machine_id)
    labels=[d.strftime('%b') for d in pivot.columns]
    heat=figure(height=max(330,45*len(shortlist)),legend=False)
    heat.add_trace(go.Heatmap(x=labels,y=pivot.index,z=pivot.values,
        colorscale=[[0,ORANGE],[0.5,'#f8f6f0'],[1,BLUE]],zmid=0,
        colorbar=dict(title=dict(text='Gap<br>$/hr')),hoverongaps=False,
        hovertemplate='%{y} · %{x}<br>Actual earnings minus peers: $%{z:,.2f}/hr<extra></extra>'))
    heat.update_layout(xaxis=dict(title_text='Month'),yaxis=dict(type='category',categoryorder='array',categoryarray=list(ordered.machine_id)))
    month_table=selected_months[['machine_id','month_start','income_gap','covered_day']].copy()
    month_table.columns=['Machine','Month','Actual earnings gap / hr','Days with peers']
    month_table['Month']=month_table['Month'].dt.strftime('%b %Y')
    history=Chart('machine-monthly-gaps','Monthly earnings gap',heat,'Machine earnings records',
        subtitle='Orange: below zone peers. Blue: above. Blank: fewer than 7 days with peer comparisons.',
        table=table(month_table,{'Actual earnings gap / hr':lambda v:fmt_money(v,2)}))
    page['sections'].append(dict(charts=[bar,history]))
    # The demand and persistence gates are visible as measured quantities, not
    # hidden behind a generic diagnosis or a single contribution ranking.
    demand=figure(height=max(330,45*len(shortlist)),legend=False)
    demand.add_trace(go.Bar(y=ordered.machine_id,x=ordered.peer_coin_in_rate_ratio*100,orientation='h',
        marker_color=ORANGE,text=[f'{v:.0%}' if pd.notna(v) else '' for v in ordered.peer_coin_in_rate_ratio],textposition='outside',
        hovertemplate='%{y}: %{x:.1f}% of zone-peer wagering<extra>January–June</extra>'))
    demand.add_vline(x=80,line_dash='dash',line_color=AXIS)
    demand.add_vline(x=100,line_color=MUTED)
    demand.update_layout(xaxis=dict(title_text='Wagering per hour as % of zone peers',ticksuffix='%',rangemode='tozero'),
        yaxis=dict(type='category',categoryorder='array',categoryarray=list(ordered.machine_id)))
    demand_chart=Chart('selection-demand','Demand shortfall · January–June',demand,'Same-date machine wagering records',
        subtitle='100% = zone peers. Dashed 80% line = selection threshold. Actual wagering, not modeled income.')
    persistence=figure(height=max(330,45*len(shortlist)),legend=False)
    persistence.add_trace(go.Bar(y=ordered.machine_id,x=ordered.persistent_months,orientation='h',marker_color=BLUE,
        text=[f'{int(n)}/{int(d)}' for n,d in zip(ordered.persistent_months,ordered.eligible_months)],textposition='outside',
        hovertemplate='%{y}: %{x} weak months<extra>Full audit gate</extra>'))
    persistence.add_vline(x=4,line_dash='dash',line_color=AXIS)
    persistence.update_layout(xaxis=dict(title_text='Months meeting the full demand gate',dtick=1,range=[0,7]),
        yaxis=dict(type='category',categoryorder='array',categoryarray=list(ordered.machine_id)))
    persistence_chart=Chart('selection-persistence','Persistence · January–June',persistence,'Monthly peer-demand analysis',
        subtitle='At least 4 weak months, including June. Gate uses actual wagering and modeled expected earnings; rules below.')
    page['sections'].append(dict(charts=[demand_chart,persistence_chart]))
    page['sections'].extend(factor_sections(shortlist,audit_result))
    return page
