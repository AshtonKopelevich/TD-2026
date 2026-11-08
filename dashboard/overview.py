"""Overview of the current cohort, observed floor results and funded July plan."""

import pandas as pd

from .action_plan import TITLES
from .charts import fmt_money, fmt_num, fmt_pct, fmt_short_money, table
from .contract import BUDGET
from .data import DB_PATH, Filters, T, _db_stamp, query
from .machine_summary import observations, selection_audit, summarize


def build():
    audit=selection_audit(_db_stamp(),str(DB_PATH))
    selected=pd.DataFrame(audit['selected'])
    machines,_=summarize(observations(Filters()))
    targets=selected[['machine_id','replacement_rank']].merge(machines,on='machine_id').sort_values('replacement_rank')
    floor=query(f'''SELECT min(gaming_date) AS start_date,max(gaming_date) AS end_date,
        count(DISTINCT gaming_date) AS gaming_days,sum(coin_in_usd) AS wagers,
        sum(house_win_usd) AS house_win,sum(actual_contribution_usd) AS contribution,
        sum(carded_coin_in_usd)::DOUBLE/nullif(sum(coin_in_usd),0) AS carded_share,
        sum(available_seconds)::DOUBLE/nullif(sum(scheduled_seconds),0) AS availability
        FROM {T('mart_machine_daily')}''').iloc[0]
    losses=query(f'''SELECT sum(estimated_lost_theo_usd) AS lost FROM {T('mart_downtime_hourly')}
        WHERE downtime_seconds>0''').iloc[0,0]
    july=query(f"SELECT sum(model_prediction_usd) AS wagers FROM {T('mart_forecast')} WHERE split='future'").iloc[0,0]
    actions=query(f'SELECT action_type_id,target_id,quantity,total_cost_usd FROM {T("mart_actions")} WHERE selected')
    allocated=actions.total_cost_usd.sum()
    grouped=actions.groupby('action_type_id',sort=False).agg(units=('quantity','sum'),amount=('total_cost_usd','sum')).reset_index()
    catalog=query('SELECT action_type_id,name FROM metadata.action_catalog')
    names=dict(zip(catalog.action_type_id,catalog['name']))
    grouped['label']=grouped.action_type_id.map(lambda key:TITLES.get(key,names.get(key,key)))
    allocations=grouped[['label','units','amount']].copy()
    allocations.columns=['July action','Units','Proposed cash cost']
    chips=[]
    positions=[(14,44),(32,53),(50,56),(68,53),(86,44),
               (22,70),(36,79),(50,82),(64,79),(78,70)]
    for r,(x,y) in zip(targets.itertuples(),positions):
        chips.append(dict(id=r.machine_id,rank=int(r.replacement_rank),zone=r.zone_name,bank=r.bank_id,
            href=f'/machines/{r.machine_id}',x=x,y=y,actual_win=fmt_money(r.income_rate,2)))
    short_table=targets[['replacement_rank','machine_id','zone_name','bank_id','income_rate','contribution_rate','wager_ratio','availability']].copy()
    short_table.columns=['Screening rank','Machine','Zone','Bank','Actual house win / hr','Actual contribution / hr','Wagering vs. zone peers','Availability']
    target_table=table(short_table,{'Actual house win / hr':lambda v:fmt_money(v,2),
        'Actual contribution / hr':lambda v:fmt_money(v,2),'Wagering vs. zone peers':fmt_pct,'Availability':fmt_pct},
        {'Machine':lambda r:'/machines/'+r.Machine})
    cards=[
        dict(endpoint='verdict',title='Machine Summary',value=f'{len(targets)} screened targets',description='Selection factors, observed earnings and replacement economics.'),
        dict(endpoint='machines',title='Machine Explorer',value=f'{len(machines)} current machines',description='Clickable floor map, peer comparisons and machine histories.'),
        dict(endpoint='demand',title='Floor Demand',value=fmt_short_money(floor.wagers)+' wagered',description='Daily demand, market context, visits and zone traffic.'),
        dict(endpoint='downtime',title='Downtime',value=fmt_short_money(losses)+' estimated loss',description='Lost Expected Value, repair timing and manufacturer breakdowns.'),
        dict(endpoint='guests',title='Players and Compensation',value=fmt_pct(floor.carded_share)+' carded wagering',description='Loyalty-player outcomes and the economic cost of rewards.'),
        dict(endpoint='forecast',title='Forecast',value=fmt_short_money(july)+' predicted July wagers',description='Actual versus predicted wagering, calculation and validation.'),
        dict(endpoint='plan',title='July Action Plan',value=fmt_money(allocated)+' allocated',description=f'{len(grouped)} action types, target-specific costs, controls and measurement plans.'),
    ]
    return dict(chips=chips,target_table=target_table,cards=cards,allocated=fmt_money(allocated),
        unallocated=fmt_money(BUDGET-allocated),action_types=len(grouped),
        allocations=table(allocations,{'Units':fmt_num,'Proposed cash cost':fmt_money}),
        gaming_days=int(floor.gaming_days),period=f'{floor.start_date:%b %d}–{floor.end_date:%b %d, %Y}',
        rail=[dict(label='Current machines',value=fmt_num(len(machines)),sub=f'At {floor.end_date:%B %d}'),
            dict(label='Actual house win',value=fmt_short_money(floor.house_win),sub='Wagers minus payouts · Jan–Jun'),
            dict(label='Machine contribution',value=fmt_short_money(floor.contribution),sub='After supplied machine costs'),
            dict(label='Availability',value=fmt_pct(floor.availability),sub='Available ÷ scheduled time'),
            dict(label='July allocation',value=fmt_money(allocated),sub=f'{len(grouped)} action types · proposed')])
