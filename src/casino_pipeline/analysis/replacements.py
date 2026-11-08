"""Read-only replacement evidence audit over published marts.

Run: python -m casino_pipeline.analysis.replacements
This does not rebuild marts, spend the budget, or claim causal replacement effects.
"""

import argparse
import csv
from datetime import date
import json
from pathlib import Path

import duckdb

from .. import constants as c


def selection_reasons(row, gap=0.20, min_months=4):
    """Explicit proposed evidence gate, separate from the economic ranking."""
    reasons = []
    if not row['current_machine']:
        reasons.append('not active at historical end')
    if row['active_days'] < c.MIN_ACTIVE_DAYS or row['positive_wager_days'] < c.MIN_POSITIVE_WAGER_DAYS:
        reasons.append('insufficient exposure')
    if row['peer_coverage_fraction'] is None or row['peer_coverage_fraction'] < c.MIN_PEER_COVERAGE_FRACTION:
        reasons.append('insufficient peer coverage')
    for field in ('peer_coin_in_rate_ratio', 'peer_rate_ratio'):
        if row[field] is None or row[field] >= 1-gap:
            reasons.append('full-period ' + field + ' does not meet gap')
    if row['persistent_months'] < min_months or not row['weak_in_final_month']:
        reasons.append('weakness not persistent through final month')
    for field in ('location_flag', 'downtime_flag', 'repair_rebound_flag', 'hold_anomaly_flag',
                  'dependence_warning', 'exposure_concentration_warning', 'method_disagreement'):
        if row[field]:
            reasons.append(field)
    if row['expected_contribution_per_available_hour'] is None:
        reasons.append('unavailable contribution rate')
    return reasons


def lease_scenario(row, action, recovery, horizon_days=30):
    """Recover a fraction of the peer theo gap; all other ongoing costs unchanged.

    Catalogue recurring charges are incremental, with no assumed saving of old
    lease costs. The peer gap is a scenario input, not an identified causal effect.
    """
    operating_days = max(0, horizon_days-int(action['lead_days']))
    install_hours = min(float(action['downtime_minutes'])/60, operating_days*24)
    availability = float(row['availability_ratio'])
    hours = max(0, operating_days*24-install_hours)*availability
    cost = (float(action['unit_cost_cents']) + operating_days*float(action['recurring_cost_cents_per_day']))/100
    gap = float(row['peer_theo_per_hour'])-float(row['theo_per_available_hour'])
    # Use expected gross earnings for shutdown loss: fixed costs do not disappear.
    shutdown_loss = install_hours*availability*float(row['theo_per_available_hour'])
    benefit = recovery*gap*hours-shutdown_loss
    break_even = (cost+shutdown_loss)/hours if hours else None
    return dict(cash_cost_usd=cost, productive_hours=hours,
                net_scenario_usd=benefit-cost, break_even_theo_uplift_per_hour=break_even)


def records(con, sql):
    result = con.execute(sql)
    names = [col[0] for col in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def audit(con):
    start, end = con.execute('SELECT min(gaming_date), max(gaming_date) FROM marts.mart_machine_daily').fetchone()
    if start != date(2025, 1, 1) or end != date(2025, 6, 30):
        raise ValueError('This proposed six-month persistence audit requires January-June 2025.')
    # Same-date, same-zone leave-one-out rates reproduce scorecard peer semantics.
    con.execute('''CREATE TEMP VIEW replacement_peer_days AS
        WITH pools AS (
          SELECT *, count(*) FILTER (WHERE available_seconds>0) OVER z AS pool_n,
            sum(available_seconds/3600.0) OVER z AS pool_hours,
            sum(coin_in_usd) FILTER (WHERE available_seconds>0) OVER z AS pool_coin,
            sum(theo_usd) FILTER (WHERE available_seconds>0) OVER z AS pool_theo
          FROM marts.mart_machine_daily
          WINDOW z AS (PARTITION BY gaming_date,zone_id)
        )
        SELECT *, available_seconds/3600.0 AS hours,
          (pool_coin-coin_in_usd)/nullif(pool_hours-available_seconds/3600.0,0) AS peer_coin_rate,
          (pool_theo-theo_usd)/nullif(pool_hours-available_seconds/3600.0,0) AS peer_theo_rate,
          pool_n-1 AS peer_count
        FROM pools WHERE available_seconds>0''')
    monthly = records(con, '''SELECT machine_id, month_start,
        count(*) AS covered_days, count(*) FILTER (WHERE coin_in_usd>0) AS wager_days,
        sum(coin_in_usd)::DOUBLE/nullif(sum(peer_coin_rate*hours),0) AS coin_ratio,
        sum(theo_usd)::DOUBLE/nullif(sum(peer_theo_rate*hours),0) AS theo_ratio,
        sum(expected_contribution_usd)::DOUBLE/nullif(sum(hours),0) AS contribution_per_hour
        FROM replacement_peer_days WHERE peer_count>=3 GROUP BY machine_id,month_start
        ORDER BY machine_id,month_start''')
    rows = records(con, '''SELECT s.*, max(d.gaming_date) AS last_active,
        max(d.gaming_date)=(SELECT max(gaming_date) FROM marts.mart_machine_daily) AS current_machine,
        arg_max(d.zone_name,d.gaming_date) AS latest_zone,
        arg_max(d.bank_id,d.gaming_date) AS latest_bank
        FROM marts.mart_machine_scorecard s JOIN marts.mart_machine_daily d USING(machine_id)
        GROUP BY ALL ORDER BY s.adjusted_rank''')
    # Test game mix as a competing explanation. Matching game characteristics
    # changes the question to within-game weakness; it does not estimate the
    # benefit of installing a different game/cabinet.
    matched = records(con, '''WITH pools AS (
        SELECT *, count(*) OVER g-1 AS matched_peers,
          (sum(coin_in_usd) OVER g-coin_in_usd)::DOUBLE /
            nullif(sum(hours) OVER g-hours,0) AS matched_coin_rate,
          (sum(theo_usd) OVER g-theo_usd)::DOUBLE /
            nullif(sum(hours) OVER g-hours,0) AS matched_theo_rate
        FROM replacement_peer_days
        WINDOW g AS (PARTITION BY gaming_date,zone_id,configured_rtp,volatility_class)
        ) SELECT machine_id, count(*) AS matched_days,
          sum(coin_in_usd)::DOUBLE/nullif(sum(matched_coin_rate*hours),0) AS matched_coin_ratio,
          sum(theo_usd)::DOUBLE/nullif(sum(matched_theo_rate*hours),0) AS matched_theo_ratio
        FROM pools WHERE matched_peers>=3 GROUP BY machine_id''')
    matched_lookup = {r['machine_id']:r for r in matched}
    for row in rows:
        months = [m for m in monthly if m['machine_id']==row['machine_id']]
        eligible = [m for m in months if m['covered_days']>=21 and m['wager_days']>=14]
        weak = [m for m in eligible if m['coin_ratio'] is not None and m['theo_ratio'] is not None
                and m['coin_ratio']<0.8 and m['theo_ratio']<0.8]
        row.update(eligible_months=len(eligible), persistent_months=len(weak),
                   weak_in_final_month=any(m['month_start']==date(2025,6,1) for m in weak))
        row['exclusion_reasons'] = '; '.join(selection_reasons(row))
        row['selection_eligible'] = not row['exclusion_reasons']
        # Missing repair evidence stays visible instead of becoming a negative test.
        row['repair_caveat'] = row['repair_evidence_status'] != 'available'
        match = matched_lookup.get(row['machine_id'],{})
        row.update(matched_days=match.get('matched_days',0),
                   matched_coin_ratio=match.get('matched_coin_ratio'),
                   matched_theo_ratio=match.get('matched_theo_ratio'))
    selected = sorted([r for r in rows if r['selection_eligible']],
                      key=lambda r:(r['expected_contribution_per_available_hour'],r['machine_id']))[:10]
    for i,row in enumerate(selected,1):
        row['replacement_rank'] = i
    action = records(con, "SELECT * FROM metadata.action_catalog WHERE action_type_id='A-REPLACE-LEASE'")[0]
    for row in selected:
        for fraction in (0.25,0.5,1.0):
            result = lease_scenario(row,action,fraction)
            row[f'lease_net_{int(fraction*100)}pct_gap_usd'] = result['net_scenario_usd']
        row['lease_cash_cost_usd'] = result['cash_cost_usd']
        row['break_even_theo_uplift_per_hour'] = result['break_even_theo_uplift_per_hour']
    sensitivity = []
    for gap in (0.10,0.20,0.30):
        for min_months in (3,4,5):
            candidates = []
            for row in rows:
                months = [m for m in monthly if m['machine_id']==row['machine_id'] and m['covered_days']>=21 and m['wager_days']>=14]
                weak = [m for m in months if m['coin_ratio'] is not None and m['theo_ratio'] is not None
                        and m['coin_ratio']<1-gap and m['theo_ratio']<1-gap]
                trial = dict(row,persistent_months=len(weak),weak_in_final_month=any(m['month_start']==date(2025,6,1) for m in weak))
                if not selection_reasons(trial,gap,min_months):
                    candidates.append(row['machine_id'])
            sensitivity.append(dict(gap=gap,min_months=min_months,eligible=len(candidates),top_ten=candidates[:10]))
    # Fail if the reconstructed full-window peers drift from the contracted scorecard.
    reconstructed = records(con, '''SELECT machine_id,
        sum(coin_in_usd)::DOUBLE/nullif(sum(peer_coin_rate*hours),0) AS coin_ratio,
        sum(theo_usd)::DOUBLE/nullif(sum(peer_theo_rate*hours),0) AS theo_ratio
        FROM replacement_peer_days WHERE peer_count>=3 GROUP BY machine_id''')
    lookup = {r['machine_id']:r for r in reconstructed}
    for row in rows:
        for a,b in [('peer_coin_in_rate_ratio','coin_ratio'),('peer_rate_ratio','theo_ratio')]:
            original, rebuilt = row[a], lookup.get(row['machine_id'],{}).get(b)
            if (original is None)!=(rebuilt is None) or (original is not None and abs(original-rebuilt)>1e-8):
                raise ValueError(f"Peer reconciliation failed: {row['machine_id']} {a}")
    return dict(analysis_start=start,analysis_end=end,rows=rows,monthly=monthly,selected=selected,sensitivity=sensitivity)


def write_outputs(result, output):
    output.mkdir(parents=True,exist_ok=True)
    for name,key in [('fleet_evidence','rows'),('monthly_evidence','monthly'),('proposed_ten','selected')]:
        rows = result[key]
        if rows:
            fields = list(dict.fromkeys(k for r in rows for k in r))
            with (output/f'{name}.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fields); writer.writeheader(); writer.writerows(rows)
    (output/'audit.json').write_text(json.dumps(result,default=str,indent=2),encoding='utf-8')
    lines = ['# Replacement selection evidence audit', '',
        'Provisional screening rule; not an established replacement ranking or an approved investment portfolio. '
        'Source: published marts, January-June 2025. The game-mix check and July economics below '
        'must be considered before claiming that these machines should be replaced.', '',
        '## Selection rule', '',
        'Current at June 30; at least 60 active and 30 positive-wager dates; at least 80% peer coverage; '
        'wagering AND theo at least 20% below same-zone peers on matching dates; weakness in at least four '
        'eligible months including June. Each month needs 21 covered and 14 positive-wager dates. '
        'Exclude positive location, downtime, repair-recovery, hold-anomaly or statistical-warning flags. '
        'Missing repair comparisons are disclosed. Rank qualifying machines by expected contribution per '
        'available hour ascending, breaking ties by machine ID. No forced padding to ten.', '',
        f"Fleet: {len(result['rows'])} historical machines; {sum(r['current_machine'] for r in result['rows'])} current; "
        f"{sum(r['selection_eligible'] for r in result['rows'])} qualify; {len(result['selected'])} selected.", '',
        '## Provisional ten from the screening rule', '',
        '| Rank | Machine | Contribution/hr | Wagering vs peers | Theo vs peers | Weak months | Repair comparison |',
        '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for r in result['selected']:
        lines.append(f"| {r['replacement_rank']} | {r['machine_id']} | ${r['expected_contribution_per_available_hour']:.2f} | "
            f"{r['peer_coin_in_rate_ratio']:.1%} | {r['peer_rate_ratio']:.1%} | {r['persistent_months']}/{r['eligible_months']} | {r['repair_evidence_status']} |")
    lines += ['', '## Competing explanation: game mix', '',
        'Same-date, same-zone peers with identical configured RTP and volatility class; exclude target; '
        'at least three peers per day. This tests weakness within comparable game characteristics. '
        'It does not fully match game title or bank position and does not test the benefit of changing games. '
        'A small matched gap weakens a cabinet-specific demand argument; lower-yield game mix may still '
        'matter economically. That requires comparing a game/settings change with a cabinet replacement.', '',
        '| Machine | Matched days | Wagering vs matched peers | Theo vs matched peers |',
        '| --- | ---: | ---: | ---: |']
    for r in result['selected']:
        coin = f"{r['matched_coin_ratio']:.1%}" if r['matched_coin_ratio'] is not None else 'Unavailable'
        theo = f"{r['matched_theo_ratio']:.1%}" if r['matched_theo_ratio'] is not None else 'Unavailable'
        lines.append(f"| {r['machine_id']} | {r['matched_days']} | {coin} | {theo} |")
    lines += ['', '## Replacement economics: scenarios, not causal estimates', '',
        'Lease prices and six-hour installation downtime come from metadata.action_catalog. '
        'Availability remains at its historical rate; all existing ongoing costs remain unchanged, '
        'and the catalogue lease fee is additional (no assumed saving of an existing lease). '
        'Replacement recovers 25%, 50% or 100% of the same-zone peer theo/hour gap. '
        'Shutdown forfeits baseline theo; fixed costs are not credited as savings. '
        'Additional replacement service/power differences and displaced play are unknown and excluded. '
        'These are explicit scenarios, not confidence intervals or measured replacement effects.', '',
        '| Machine | July cash cost | Break-even theo uplift/hr | Net: 25% gap | Net: 50% gap | Net: 100% gap |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in result['selected']:
        lines.append(f"| {r['machine_id']} | ${r['lease_cash_cost_usd']:,.0f} | ${r['break_even_theo_uplift_per_hour']:.2f} | "
            f"${r['lease_net_25pct_gap_usd']:,.0f} | ${r['lease_net_50pct_gap_usd']:,.0f} | ${r['lease_net_100pct_gap_usd']:,.0f} |")
    lines += ['', '## Threshold sensitivity', '', '| Peer gap | Weak months required | Eligible | Top ten |', '| --- | ---: | ---: | --- |']
    for r in result['sensitivity']:
        lines.append(f"| {r['gap']:.0%} | {r['min_months']} | {r['eligible']} | {', '.join(r['top_ten'])} |")
    lines += ['', '## Evidence and limits', '',
        '- Fleet CSV records every machine and its exclusion reasons; monthly CSV records all peer ratios. Reconstructed peer ratios reconcile to the existing scorecard within 1e-8.',
        '- The persistence test is retrospective. It is not a frozen machine-model holdout or independent confirmation of a data-selected finding.',
        '- Peer comparisons share dates and zones but do not fully adjust game mix, player preferences or location within a bank. Placement and bank diagnostics remain supporting investigations.',
        '- Existing bootstrap intervals concern payout residuals, not rank uncertainty. Threshold sensitivity is not a confidence probability.',
        '- Unflagged repair evidence can mean no detected rebound; unavailable repair evidence does not establish that faults are absent.',
        '- Expected contribution covers supplied machine costs, not complete property profit. Low contribution is not itself a measured replacement effect.',
        '- The pipeline action mart remains unchanged. An investment recommendation still needs defensible replacement-performance assumptions and comparison with repair/move alternatives.', '']
    (output/'evidence.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    root=Path(__file__).resolve().parents[3]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=root/'output/casino.duckdb')
    parser.add_argument('--output',type=Path,default=root/'output/replacement_audit')
    args=parser.parse_args()
    with duckdb.connect(str(args.database),read_only=True) as con:
        result=audit(con)
    write_outputs(result,args.output)
    print((args.output/'evidence.md').read_text(encoding='utf-8'))


if __name__=='__main__':
    main()
