"""Price explicit proposals; never infer causal benefits or auto-spend the budget."""

import csv
from datetime import date,datetime,time,timedelta
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import hashlib
import io
import json
from pathlib import Path

from . import constants as c
from .descriptive import MartContract,check_query,validate_contract
from .machine_daily import MONEY


ACTIONS = MartContract('mart_actions',('proposal_line_id',),{
    **dict.fromkeys('proposal_line_id action_type_id target_id target_type'.split(),'VARCHAR'),
    'selected':'BOOLEAN','quantity':'BIGINT','horizon_start':'DATE','horizon_end':'DATE','lead_days':'BIGINT',
    **dict.fromkeys('effective_operating_days action_downtime_hours benefit_days_per_unit'.split(),'DOUBLE'),
    **dict.fromkeys('unit_cost_usd recurring_cost_per_day_usd additional_comp_cost_usd total_cost_usd benefit_before_action_cost_usd benefit_low_usd benefit_high_usd net_benefit_usd half_effect_net_benefit_usd downtime_opportunity_cost_usd_per_hour forecast_no_action_coin_in_usd'.split(),MONEY),
    **dict.fromkeys('effect_assumption cost_assumption evidence_refs measurement_metric control_definition limitation benefit_status unit_start_dates'.split(),'VARCHAR'),
    'affected_machine_count':'BIGINT','forecast_allocation_share':'DOUBLE',
},frozenset('benefit_before_action_cost_usd benefit_low_usd benefit_high_usd net_benefit_usd half_effect_net_benefit_usd downtime_opportunity_cost_usd_per_hour forecast_no_action_coin_in_usd forecast_allocation_share'.split()))
CONTRACTS = (ACTIONS,)
REQUIRED_HEADERS = {'proposal_line_id','action_type_id','target_type','target_id','selected','quantity','effect_assumption','evidence_refs'}
UNIT_TARGET = {'machine':'machine','bank':'bank','manufacturer':'manufacturer','zone':'zone',
    'technician_shift':'shift','pilot':'property','policy':'property','event':'property','month':'property','none':'property'}
INFORMATION_ACTIONS = {'A-INSPECT','A-SURVEY','A-COMP-PILOT'}


def amount(value,default=None):
    if value is None or str(value).strip()=='':
        return default
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f'Invalid numeric proposal value: {value}') from error
    if not result.is_finite():
        raise ValueError('Proposal amounts must be finite')
    return result


def rounded(value):
    return value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def price(action,quantity,horizon_days):
    operating_days = max(0,horizon_days-int(action['lead_days']))
    unit = Decimal(int(action['unit_cost_cents']))/100
    recurring = Decimal(int(action['recurring_cost_cents_per_day']))/100
    return unit,recurring,operating_days,rounded(quantity*(unit+recurring*operating_days))


def prepare_proposal(raw,action,machine_ids,forecast):
    """Uplift inputs are per action unit/day BEFORE costs charged to this proposal."""
    line = {key:str(value).strip() if value is not None else '' for key,value in raw.items()}
    for name in ('proposal_line_id','target_type','target_id'):
        if not line.get(name):
            raise ValueError(f'Proposal requires {name}')
    if line.get('selected','').lower() not in ('true','false','1','0'):
        raise ValueError('selected must explicitly be true or false')
    selected = line['selected'].lower() in ('true','1')
    try:
        quantity = int(line.get('quantity',''))
    except ValueError as error:
        raise ValueError('Proposal quantity must be a positive integer') from error
    if quantity<=0 or quantity>int(action['quantity_limit']):
        raise ValueError('Proposal exceeds quantity limits')
    expected_target = UNIT_TARGET.get(action['unit'])
    if expected_target is None or line['target_type']!=expected_target:
        raise ValueError('Proposal target type does not match catalogue unit')
    if line['target_type'] in ('machine','bank','zone','manufacturer') and quantity!=1:
        raise ValueError('Use one explicit machine/bank/zone/manufacturer target per proposal row')
    start,end = map(date.fromisoformat,(c.FORECAST_START,c.FORECAST_END))
    horizon = (end-start).days+1
    unit,recurring,operating_days,base_cost = price(action,quantity,horizon)
    extra_comp = amount(line.get('additional_comp_cost_usd'),Decimal(0))
    opportunity = amount(line.get('downtime_opportunity_cost_usd_per_hour'))
    allocation = amount(line.get('forecast_allocation_share'))
    if extra_comp<0 or (opportunity is not None and opportunity<0) or (allocation is not None and not 0<=allocation<=1):
        raise ValueError('Costs must be nonnegative; forecast allocation must be a fraction in [0,1]')
    earliest = start+timedelta(days=int(action['lead_days']))
    starts = [date.fromisoformat(d.strip()) for d in line.get('unit_start_dates','').split(';') if d.strip()]
    if starts and len(starts)!=quantity:
        raise ValueError('unit_start_dates must specify exactly one date per unit')
    if not starts:
        if selected and action['unit']=='event':
            raise ValueError('A funded promotion requires explicit unit_start_dates')
        starts = [earliest]*quantity
    if any(d<earliest or (d>end and operating_days>0) for d in starts):
        raise ValueError('Action starts before its lead time or outside the horizon')
    if len(set(starts))>1 and action['unit']!='event':
        raise ValueError('Use separate proposal rows for non-event units with different activation dates')
    downtime_per_machine = min(Decimal(int(action['downtime_minutes']))/60,Decimal(operating_days*24))
    affected = len(machine_ids) if action['unit']!='none' else 0
    # Bank and manufacturer downtime is per affected machine, not just one package.
    downtime_hours = downtime_per_machine*affected
    available_days = min(max(Decimal(0),Decimal((end-d).days+1)-downtime_per_machine/24) for d in starts)
    benefit_days = amount(line.get('benefit_days_per_unit'),available_days)
    if not 0<=benefit_days<=available_days:
        raise ValueError('benefit_days_per_unit exceeds the lead-time/downtime-adjusted horizon')
    if selected and action['unit']=='event' and not line.get('benefit_days_per_unit'):
        raise ValueError('A funded promotion requires explicit benefit_days_per_unit')
    if action['unit']=='event':
        ordered = sorted(starts)
        if any(Decimal((b-a).days)<benefit_days for a,b in zip(ordered,ordered[1:])):
            raise ValueError('Promotion units may not overlap')
    rates = [amount(line.get(key)) for key in ('expected_uplift_usd_per_day','low_uplift_usd_per_day','high_uplift_usd_per_day')]
    if any(v is not None for v in rates) and not all(v is not None for v in rates):
        raise ValueError('Supply expected, low and high daily uplift together')
    expected,low,high = rates
    if expected is not None and not low<=expected<=high:
        raise ValueError('Daily uplift scenarios must satisfy low <= expected <= high')
    if selected and action['action_type_id']!='A-HOLD':
        for key in ('effect_assumption','cost_assumption','evidence_refs','measurement_metric','control_definition','limitation'):
            if not line.get(key):
                raise ValueError(f'Funded action requires {key}')
        if expected is None and action['action_type_id'] not in INFORMATION_ACTIONS:
            raise ValueError('Funded financial actions require explicit uplift scenarios')
        if expected is not None and downtime_hours>0 and opportunity is None:
            raise ValueError('Funded action with downtime requires an explicit opportunity-cost rate (zero is allowed)')
        if action['incompatibility_group']=='comp_policy' and not line.get('additional_comp_cost_usd'):
            raise ValueError('Comp proposals must explicitly budget additional comp cost, including zero')
    total_cost = rounded(base_cost+extra_comp)
    benefit = benefit_low = benefit_high = net = half = None
    if action['action_type_id']=='A-HOLD':
        if total_cost!=0 or expected is not None:
            raise ValueError('Preserving the budget must have zero cost and no uplift claim')
        benefit=benefit_low=benefit_high=net=half=Decimal('0.00')
        status = 'preserve_budget'
    elif expected is not None and (downtime_hours==0 or opportunity is not None):
        downtime_cost = downtime_hours*(opportunity or 0)
        benefit,benefit_low,benefit_high = [rounded(quantity*r*benefit_days-downtime_cost) for r in (expected,low,high)]
        net,half = rounded(benefit-total_cost),rounded(benefit*Decimal('.5')-total_cost)
        status = 'configured_scenario'
    else:
        status = 'information_only' if expected is None and action['action_type_id'] in INFORMATION_ACTIONS else 'benefit_unconfigured'
    forecast_context = None
    if allocation is not None:
        weights = {}
        for activation in starts:
            remaining = benefit_days
            d = activation
            while remaining>0:
                weight = min(Decimal(1),remaining)
                weights[d] = max(weights.get(d,Decimal(0)),weight)
                remaining -= weight
                d += timedelta(days=1)
        if set(weights)-set(forecast):
            raise ValueError('Missing forecast dates for proposed action context')
        forecast_context = rounded(sum(forecast[d]*w for d,w in weights.items())*allocation)
    return {
        'proposal_line_id':line['proposal_line_id'],'action_type_id':action['action_type_id'],
        'target_type':line['target_type'],'target_id':line['target_id'],'selected':selected,'quantity':quantity,
        'horizon_start':start,'horizon_end':end,'lead_days':int(action['lead_days']),
        'effective_operating_days':float(operating_days),'action_downtime_hours':float(downtime_hours),
        'benefit_days_per_unit':float(benefit_days),'unit_cost_usd':unit,'recurring_cost_per_day_usd':recurring,
        'additional_comp_cost_usd':rounded(extra_comp),'total_cost_usd':total_cost,
        'benefit_before_action_cost_usd':benefit,'benefit_low_usd':benefit_low,'benefit_high_usd':benefit_high,
        'net_benefit_usd':net,'half_effect_net_benefit_usd':half,
        **{key:line.get(key,'') for key in ('effect_assumption','cost_assumption','evidence_refs','measurement_metric','control_definition','limitation')},
        'benefit_status':status,'unit_start_dates':';'.join(d.isoformat() for d in starts),
        'affected_machine_count':affected,'downtime_opportunity_cost_usd_per_hour':rounded(opportunity) if opportunity is not None else None,
        'forecast_allocation_share':float(allocation) if allocation is not None else None,
        'forecast_no_action_coin_in_usd':forecast_context,
    }


def validate_portfolio(rows,catalog,target_sets):
    if len({r['proposal_line_id'] for r in rows})!=len(rows):
        raise ValueError('Duplicate proposal_line_id')
    selected = [r for r in rows if r['selected']]
    if sum(r['total_cost_usd'] for r in selected)>Decimal(c.ACTION_BUDGET_USD):
        raise ValueError('Selected portfolio exceeds budget')
    if len({r['action_type_id'] for r in selected if r['action_type_id']!='A-HOLD'})>c.MAX_FUNDED_ACTION_TYPES:
        raise ValueError('Selected portfolio exceeds action-type limit')
    for action_id in {r['action_type_id'] for r in selected}:
        if sum(r['quantity'] for r in selected if r['action_type_id']==action_id)>catalog[action_id]['quantity_limit']:
            raise ValueError('Aggregate selected quantity exceeds catalogue limit')
    for i,a in enumerate(selected):
        group = catalog[a['action_type_id']]['incompatibility_group']
        for b in selected[i+1:]:
            other_group = catalog[b['action_type_id']]['incompatibility_group']
            if (a['action_type_id']==b['action_type_id'] and a['target_type'] in ('machine','bank','zone','manufacturer')
                    and a['target_id']==b['target_id']):
                raise ValueError('Duplicate selected target for the same action')
            if a['action_type_id']==b['action_type_id'] and catalog[a['action_type_id']]['unit']=='event':
                left = [date.fromisoformat(d) for d in a['unit_start_dates'].split(';')]
                right = [date.fromisoformat(d) for d in b['unit_start_dates'].split(';')]
                if any((x-y).days<b['benefit_days_per_unit'] and (y-x).days<a['benefit_days_per_unit'] for x in left for y in right):
                    raise ValueError('Selected promotion windows overlap')
            if group and group==other_group and (group=='comp_policy' or target_sets[a['proposal_line_id']]&target_sets[b['proposal_line_id']]):
                raise ValueError('Selected actions conflict on expanded targets or comp policy')


def build_actions(con,proposal_path):
    payload = Path(proposal_path).read_bytes()
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    if not REQUIRED_HEADERS<=set(reader.fieldnames or ()):
        raise ValueError('Action proposal CSV is missing required headers')
    raw_rows = [row for row in reader if any(str(v or '').strip() for v in row.values())]
    if any(None in row for row in raw_rows):
        raise ValueError('Malformed proposal CSV row')
    cursor = con.execute('SELECT * FROM raw.action_catalog')
    names = [d[0] for d in cursor.description]
    catalog = {r['action_type_id']:r for r in (dict(zip(names,row)) for row in cursor.fetchall())}
    start = date.fromisoformat(c.FORECAST_START)
    local_start = datetime.combine(start,time(c.GAMING_DAY_START_HOUR))
    origin = con.execute("SELECT timezone('UTC',timezone(?::VARCHAR,?::TIMESTAMP))",[c.LOCAL_TIMEZONE,local_start]).fetchone()[0]
    current = con.execute('''SELECT p.machine_id,l.bank_id,l.zone_id,m.manufacturer FROM raw.placements p
      JOIN raw.floor_locations l ON l.location_id=p.location_id JOIN raw.machines m USING(machine_id)
      WHERE p.effective_from_utc<=? AND (p.effective_to_utc IS NULL OR p.effective_to_utc>?)''',[origin,origin]).fetchall()
    targets = {('property','property'):{r[0] for r in current}}
    for machine,bank,zone,manufacturer in current:
        for kind,key in (('machine',machine),('bank',bank),('zone',zone),('manufacturer',manufacturer)):
            targets.setdefault((kind,key),set()).add(machine)
    for zone, in con.execute("SELECT location_id FROM raw.floor_locations WHERE node_type='zone'").fetchall():
        targets.setdefault(('zone',zone),set())
    for shift, in con.execute('SELECT DISTINCT shift FROM raw.shift_roster').fetchall():
        targets['shift',shift] = targets['property','property'].copy()
    forecast = dict(con.execute("SELECT forecast_date,model_prediction_usd FROM marts.mart_forecast WHERE split='future'").fetchall())
    rows,target_sets = [],{}
    for raw in raw_rows:
        action_id = (raw.get('action_type_id') or '').strip()
        if action_id not in catalog:
            raise ValueError(f'Unknown action_type_id: {action_id}')
        key = ((raw.get('target_type') or '').strip(),(raw.get('target_id') or '').strip())
        if key not in targets:
            raise ValueError(f'Unknown/inactive action target: {key}')
        result = prepare_proposal(raw,catalog[action_id],targets[key],forecast)
        rows.append(result)
        target_sets[result['proposal_line_id']] = targets[key]
    validate_portfolio(rows,catalog,target_sets)
    con.execute('CREATE TABLE marts.mart_actions ('+','.join(f'"{k}" {v}' for k,v in ACTIONS.columns.items())+')')
    if rows:
        con.executemany('INSERT INTO marts.mart_actions VALUES ('+','.join('?' for _ in ACTIONS.columns)+')',
                        [[row[k] for k in ACTIONS.columns] for row in rows])
    sql = Path(__file__).resolve().parents[2]/'sql'/'marts'/'actions.sql'
    con.execute(sql.read_text(encoding='utf-8'))
    config = {'path':str(Path(proposal_path).resolve()),'sha256':hashlib.sha256(payload).hexdigest(),
              'rows':len(rows),'headers':reader.fieldnames,'proposals':raw_rows}
    con.execute('CREATE TABLE metadata.action_configuration AS SELECT ?::JSON AS document',[json.dumps(config)])
    con.execute('CREATE TABLE diagnostics.action_targets (proposal_line_id VARCHAR,machine_id VARCHAR)')
    expanded = [(key,machine) for key,machines in target_sets.items() for machine in sorted(machines)]
    if expanded:
        con.executemany('INSERT INTO diagnostics.action_targets VALUES (?,?)',expanded)
    selected = [r for r in rows if r['selected']]
    spend = sum((r['total_cost_usd'] for r in selected),Decimal(0))
    net = sum((r['net_benefit_usd'] for r in selected),Decimal(0)) if all(r['net_benefit_usd'] is not None for r in selected) else None
    state = 'no_proposals' if not rows else 'draft_only' if not selected else 'selected_portfolio'
    con.execute('''CREATE TABLE diagnostics.action_portfolio AS SELECT ?::VARCHAR AS status,?::BIGINT AS proposal_rows,
      ?::BIGINT AS selected_rows,?::BIGINT AS funded_action_types,?::DECIMAL(24,2) AS budget_usd,
      ?::DECIMAL(24,2) AS spent_usd,?::DECIMAL(24,2) AS unallocated_usd,?::DECIMAL(24,2) AS scenario_net_benefit_usd,
      'Effects are configured scenarios, not causal forecasts; overlapping benefits may not be additive. Destination feasibility is not solved.'::VARCHAR AS limitation''',[
        state,len(rows),len(selected),len({r['action_type_id'] for r in selected if r['action_type_id']!='A-HOLD'}),
        Decimal(c.ACTION_BUDGET_USD),spend,Decimal(c.ACTION_BUDGET_USD)-spend,net if selected else None])
    return config


def validate_actions(con):
    checks = validate_contract(con,ACTIONS)
    queries = {
      'budget':f"SELECT count(*) FROM diagnostics.action_portfolio WHERE spent_usd>{c.ACTION_BUDGET_USD} OR unallocated_usd<0 OR funded_action_types>{c.MAX_FUNDED_ACTION_TYPES}",
      'cost_identities':'''SELECT count(*) FROM marts.mart_actions WHERE total_cost_usd<0
        OR total_cost_usd<>quantity*(unit_cost_usd+recurring_cost_per_day_usd*effective_operating_days::BIGINT)+additional_comp_cost_usd
        OR (net_benefit_usd IS NOT NULL AND net_benefit_usd<>benefit_before_action_cost_usd-total_cost_usd)
        OR benefit_low_usd>benefit_before_action_cost_usd OR benefit_before_action_cost_usd>benefit_high_usd''',
    }
    checks.extend(check_query(con,'actions.'+name,sql) for name,sql in queries.items())
    return checks
