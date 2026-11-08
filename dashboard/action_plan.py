"""Concrete proposed actions, evidence, costs and honest scenario accounting."""

import html

import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

from .charts import BAND, GRID, SERIES, SURFACE, Chart, figure, fmt_money, fmt_num, table
from .contract import BUDGET, MAX_ACTION_TYPES
from .data import T, query, zone_name


TITLES={'A-REPLACE-LEASE':'Lease replacements for ten screened machines',
        'A-INSPECT':'Inspect payout settings and meters',
        'A-PREVENTIVE':'Preventive maintenance by manufacturer',
        'A-WAYFINDING':'Improve Back Forty signage',
        'A-SURVEY':'Expand the guest survey',
        'A-PROMO':'Run the July 18–20 promotion',
        'A-COMP-PILOT':'Test a lower-cost loyalty reward mix'}
OUTCOMES={
    'A-REPLACE-LEASE':'Lease new titles for all ten screened machines. Measure actual wagering, contribution and availability against preassigned unchanged controls before renewal or further expansion.',
    'A-INSPECT':'Inspect all ten replacement candidates before installation, plus the separate payout-anomaly lead. Document configurations, meter checks and any corrective work.',
    'A-PREVENTIVE':'Service all three manufacturer fleets in staggered bank groups. Track fault downtime and repeat tickets before and after the sweep.',
    'A-WAYFINDING':'Refresh signage and sightlines in the lowest-wagering zone. Measure entry-to-play conversion and actual contribution, allowing for changes elsewhere on the floor.',
    'A-SURVEY':'Expand zone- and time-stratified guest interviews to distinguish title preferences, visibility and service issues. Include carded and uncarded visitors.',
    'A-PROMO':'Fund one general property promotion after the catalogue lead time. Use an audience holdout and the no-action wagering forecast to evaluate the response.',
    'A-COMP-PILOT':'Test equal-value reward choices with different economic costs while preserving existing entitlements. Measure cost per redemption; do not target increased gambling.',
}


def net_scenarios(actions):
    quantified=actions[actions.net_benefit_usd.notna()].copy()
    # Contract bounds are BEFORE proposal charges; convert to net exactly once.
    quantified['net_low']=quantified.benefit_low_usd-quantified.total_cost_usd
    quantified['net_high']=quantified.benefit_high_usd-quantified.total_cost_usd
    return quantified


def action_cards(actions,catalog,f):
    from .pages import _evidence_links
    cards=[]
    for code,rows in actions.groupby('action_type_id',sort=False):
        title=TITLES.get(code,catalog.get(code,code))
        cost=rows.total_cost_usd.sum()
        targets=[]
        detail=[]
        for r in rows.itertuples():
            if r.target_type=='machine':
                target=f'<a href="/machines/{html.escape(r.target_id)}">{html.escape(r.target_id)}</a>'
            elif r.target_type=='zone':
                target=f'<a href="/demand?zone={html.escape(r.target_id)}">{html.escape(zone_name(r.target_id))}</a>'
            elif r.target_type=='manufacturer':
                target=f'<a href="/downtime">{html.escape(r.target_id)} fleet</a>'
            else:
                target='Casino guests · property-wide programme'
            targets.append(target)
            labels={
                'Evidence and proposed effect':r.effect_assumption,
                'Cost basis':r.cost_assumption,
                'Measurement and decision rule':r.measurement_metric,
                'Comparison / control':r.control_definition,
                'Uncertainty and limitations':r.limitation,
            }
            dl=''.join(f'<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>' for k,v in labels.items())
            evidence=_evidence_links(r.evidence_refs,f)
            detail.append(f'<section class="proposal-detail"><h4>{html.escape(r.proposal_line_id)} · {html.escape(r.target_id)}</h4>'
                f'<dl>{dl}<dt>Supporting analysis</dt><dd>{evidence}</dd></dl></section>')
        start=min(d for value in rows.unit_start_dates for d in value.split(';') if d)
        cards.append(f'<article class="action-card"><header><h3>{html.escape(title)}</h3>'
            f'<p class="action-money"><span>{fmt_money(cost)}</span> proposed cost · {int(rows.quantity.sum())} unit(s)</p></header>'
            f'<p class="action-targets">'+', '.join(targets)+'</p>'
            f'<p>{html.escape(OUTCOMES.get(code,"See the proposal measurement plan."))}</p>'
            f'<p class="source">Earliest activation: {html.escape(start)} · {int(rows.lead_days.max())}-day lead time</p>'
            f'<details class="proposal-evidence"><summary>Evidence, assumptions and July measurement plan</summary>'+''.join(detail)+'</details></article>')
    return Markup('<div class="action-cards">'+''.join(cards)+'</div>')


def build(f):
    actions=query(f'SELECT * FROM {T("mart_actions")} WHERE selected ORDER BY proposal_line_id')
    if actions.empty:
        return dict(title_override='July Action Plan',compact=True,headline='',no_filters=True,
            scope_note='July 1–30, 2025 · proposed operations budget',
            sections=[dict(title='No portfolio configured',intro='The proposal configuration has no selected actions. This is a configuration state, not a finding that no action is justified.')])
    catalogue=query('SELECT action_type_id,name,quantity_limit FROM metadata.action_catalog')
    names=dict(zip(catalogue.action_type_id,catalogue['name']))
    actions['label']=actions.action_type_id.map(lambda code:TITLES.get(code,names.get(code,code)))
    grouped=actions.groupby(['action_type_id','label'],sort=False).agg(units=('quantity','sum'),amount=('total_cost_usd','sum')).reset_index()
    spent=actions.total_cost_usd.sum()
    reserve=BUDGET-spent
    fig=figure(height=260,barmode='stack')
    for i,r in enumerate(grouped.itertuples()):
        fig.add_trace(go.Bar(x=[r.amount],y=['July budget'],name=r.label,orientation='h',
            marker=dict(color=SERIES[i%len(SERIES)],line=dict(color=SURFACE,width=2)),
            hovertemplate=html.escape(r.label)+': $%{x:,.0f}<extra></extra>'))
    if reserve>0:
        fig.add_trace(go.Bar(x=[reserve],y=['July budget'],name='Unallocated',orientation='h',
            marker=dict(color=BAND,line=dict(color=SURFACE,width=2)),hovertemplate='Unallocated: $%{x:,.0f}<extra></extra>'))
    fig.update_layout(xaxis=dict(range=[0,BUDGET],tickprefix='$',tickformat='~s',showgrid=True,gridcolor=GRID),yaxis=dict(visible=False),margin=dict(t=105))
    budget_table=grouped[['label','units','amount']].copy()
    budget_table.columns=['Action type','Units','Proposed cash cost']
    budget=Chart('plan-budget','Allocation of the $100,000 July budget',fig,'Validated proposal costs',wide=True,
        table=table(budget_table,{'Units':fmt_num,'Proposed cash cost':fmt_money}),
        note='Full cash allocation; proposals do not execute real operations.')
    lines=actions[['proposal_line_id','label','target_id','quantity','unit_start_dates','lead_days',
        'benefit_days_per_unit','action_downtime_hours','total_cost_usd','benefit_status']].copy()
    lines['benefit_status']=lines.benefit_status.map({'configured_scenario':'Assumption-based financial scenario',
        'information_only':'Diagnostic / experimental decision outcome','preserve_budget':'Reserve'})
    lines.columns=['Proposal','Action','Target','Units','Earliest activation','Lead days','Benefit days per unit',
        'Installation downtime (machine-hours)','Cash cost','Benefit basis']
    quantified=net_scenarios(actions)
    def target_href(row):
        original=actions[actions.proposal_line_id==row.Proposal].iloc[0]
        if original.target_type=='machine':
            return '/machines/'+original.target_id
        if original.target_type=='zone':
            return '/demand?zone='+original.target_id
        return '/downtime' if original.target_type=='manufacturer' else '/demand'
    sections=[dict(title='Proposed actions',blocks=[action_cards(actions,names,f)]),dict(charts=[budget]),
        dict(title='Costs and timing',blocks=[table(lines,{'Units':fmt_num,'Benefit days per unit':lambda v:fmt_num(v,2),
            'Installation downtime (machine-hours)':lambda v:fmt_num(v,1),'Cash cost':fmt_money},
            {'Target':target_href})],source='Validated action catalogue and proposed targets')]
    if not quantified.empty:
        scenario=quantified[['label','target_id','total_cost_usd','net_low','net_benefit_usd','net_high','half_effect_net_benefit_usd']].copy()
        scenario.columns=['Action','Target','Cash cost','Low net scenario','Central net scenario','High net scenario','Half-effect net scenario']
        sections.append(dict(title='Financial scenarios by action and target',
            intro='Each action has its own explicit low, central and high assumptions in the evidence details. These are not measured causal effects or confidence intervals. Cash costs and catalogue shutdowns are included. Overlapping interventions prevent an independently additive portfolio-return claim; July net scenarios can be negative.',
            blocks=[table(scenario,{c:fmt_money for c in scenario.columns if c not in ['Action','Target']})],
            source='Explicit action scenarios and catalogue prices'))
    limits=dict(zip(catalogue.action_type_id,catalogue.quantity_limit))
    funded=set(actions.action_type_id)-{'A-HOLD'}
    units=actions.groupby('action_type_id').quantity.sum()
    checks=[(spent==BUDGET,f'{fmt_money(spent)} allocated; {fmt_money(reserve)} unallocated'),
        (all(qty<=limits[code] for code,qty in units.items()),'Catalogue quantity limits respected')]
    if funded & {'A-COMP-PILOT','A-COMP-CHANGE'}:
        checks.append((not ({'A-COMP-PILOT','A-COMP-CHANGE'}<=funded),'No conflicting reward pilot and floor-wide policy change'))
    if MAX_ACTION_TYPES is not None:
        checks.append((len(funded)<=MAX_ACTION_TYPES,f'{len(funded)} funded action types; limit {MAX_ACTION_TYPES}'))
    checks_html=Markup('<ul class="checks">'+''.join(
        f'<li class="{"ok" if passed else "fail"}"><span>{"✓" if passed else "✕"}</span>{html.escape(label)}</li>' for passed,label in checks)+'</ul>')
    sections.append(dict(title='Portfolio checks',blocks=[checks_html]))
    return dict(title_override='July Action Plan',compact=True,headline='',no_filters=True,
        scope_note='July 1–30, 2025 · proposed portfolio · effects and controls are prospective',
        rail=[dict(label='Proposed spending',value=fmt_money(spent),sub='Within the $100,000 budget'),
            dict(label='Unallocated',value=fmt_money(reserve),sub='Full budget allocated'),
            dict(label='Funded action types',value=str(len(funded)),sub=f'{len(actions)} explicit proposal lines; no type cap'),
            dict(label='Leased replacements',value=fmt_num(actions.loc[actions.action_type_id=='A-REPLACE-LEASE','quantity'].sum()),sub='All ten screened candidates'),
            dict(label='Inspection targets',value=fmt_num(actions.loc[actions.action_type_id=='A-INSPECT','quantity'].sum()),sub='Ten prechecks plus the payout lead')],
        sections=sections+[dict(title='Expected decision outcomes',intro='The programme replaces the ten screened machines, verifies configurations, addresses fault losses and zone visibility, and tests guest response. Inspection and survey information benefits are unpriced; their costs are fully budgeted. Full allocation follows the requested budget constraint, not a claim that all actions maximize July profit.')])
