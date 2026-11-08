"""Generate a priced, evidence-linked July pilot portfolio from published marts.

Effects are explicit scenarios. No operations are executed by this script.
"""

import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import duckdb

from .analysis.replacements import audit, records
from .actions import prepare_proposal, validate_portfolio


ROOT=Path(__file__).resolve().parents[2]
FIELDS='proposal_line_id action_type_id target_type target_id selected quantity effect_assumption cost_assumption evidence_refs measurement_metric control_definition limitation expected_uplift_usd_per_day low_uplift_usd_per_day high_uplift_usd_per_day benefit_days_per_unit downtime_opportunity_cost_usd_per_hour additional_comp_cost_usd forecast_allocation_share unit_start_dates'.split()


def dollars(value):
    return str(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def generate(con):
    screened=audit(con)['selected']
    if len(screened)!=10:
        raise ValueError('Ten screened replacement candidates are required for the full-budget portfolio.')
    proposals=[]
    evidence=[]
    treated={row['machine_id'] for row in screened}
    for i,candidate in enumerate(screened,1):
        mid=candidate['machine_id']
        # Reconstruct observed same-date zone-peer earnings, independently of
        # modeled income. Keep game-mix limitations explicit in the proposal.
        actual=records(con,f'''WITH pools AS (
            SELECT *,sum(house_win_usd) FILTER(WHERE available_seconds>0) OVER z AS zone_income,
              sum(available_seconds) OVER z/3600.0 AS zone_hours,
              count(*) FILTER(WHERE available_seconds>0) OVER z AS n
            FROM marts.mart_machine_daily WINDOW z AS (PARTITION BY gaming_date,zone_id)
          ) SELECT machine_id,sum(house_win_usd)::DOUBLE/sum(available_seconds)*3600 AS actual_rate,
            sum((zone_income-house_win_usd)/nullif(zone_hours-available_seconds/3600.0,0)*available_seconds/3600.0)
              /nullif(sum(available_seconds)/3600.0,0) AS peer_rate,
            sum(available_seconds)::DOUBLE/sum(scheduled_seconds) AS availability,
            arg_max(zone_id,gaming_date) AS zone_id,arg_max(bank_id,gaming_date) AS bank_id,
            arg_max(theme,gaming_date) AS theme
          FROM pools WHERE machine_id='{mid}' AND available_seconds>0 AND n-1>=3 GROUP BY machine_id''')[0]
        current=con.execute('SELECT max(gaming_date) FROM marts.mart_machine_daily').fetchone()[0]
        controls=con.execute('''SELECT d.machine_id,arg_max(d.theme,d.gaming_date) AS theme,
            sum(d.coin_in_usd)::DOUBLE/nullif(sum(d.available_seconds)/3600.0,0) AS wager_rate
            FROM marts.mart_machine_daily d JOIN marts.mart_machine_daily latest
              ON latest.machine_id=d.machine_id AND latest.gaming_date=?
            JOIN marts.mart_machine_scorecard s ON s.machine_id=d.machine_id
            WHERE latest.zone_id=? AND latest.bank_id<>? AND d.machine_id NOT IN (SELECT unnest(?))
              AND s.active_days>=60 AND NOT s.method_disagreement AND NOT s.exposure_concentration_warning
              AND NOT coalesce(s.dependence_warning,true) AND NOT coalesce(s.hold_anomaly_flag,true)
            GROUP BY d.machine_id
            ORDER BY CASE WHEN arg_max(d.theme,d.gaming_date)=? THEN 0 ELSE 1 END,
              abs(wager_rate-?),d.machine_id LIMIT 1''',
            [current,actual['zone_id'],actual['bank_id'],sorted(treated),actual['theme'],candidate['coin_in_per_available_hour']]).fetchone()
        if controls is None:
            raise ValueError(f'No unchanged other-bank control for {mid}')
        control_description=('same game and zone' if controls[1]==actual['theme'] else
            'same zone, different game; imperfect game-mix comparison')
        gap=max(0,actual['peer_rate']-actual['actual_rate'])
        if gap<=0:
            raise ValueError(f'{mid} has no observed zone-peer earnings shortfall to scenario-test')
        daily=gap*24*actual['availability']
        opportunity=max(0,actual['actual_rate'])*actual['availability']
        proposals.append(dict(proposal_line_id=f'JUL-LEASE-{i:02d}',action_type_id='A-REPLACE-LEASE',
            target_type='machine',target_id=mid,selected='true',quantity=1,
            effect_assumption=f'Lease a new title for this screened machine as part of the ten-machine replacement programme. {mid} is audited candidate #{candidate["replacement_rank"]}, with wagering {candidate["peer_coin_in_rate_ratio"]:.1%} of zone peers and weakness in {candidate["persistent_months"]}/{candidate["eligible_months"]} months. Actual earnings are ${actual["actual_rate"]:.2f}/available hour versus ${actual["peer_rate"]:.2f} for same-date zone peers. Central scenario recovers 50% of that observed ${gap:.2f}/hour gap; low 0%, high 100%, at historical availability. These are assumptions, not a measured replacement effect.',
            cost_assumption='One unit: $2500 setup plus $55 per day for 16 operating days after the 14-day lead; six-hour installation. All current ongoing machine costs held unchanged; no credited savings of old lease costs. New lease charges appear only in proposal cost. Additional service/power differences excluded.',
            evidence_refs='mart_machine_scorecard;mart_machine_daily;mart_machine_month',
            measurement_metric='Track actual wagering and house win per available hour, availability and supplied-cost contribution; report payout uncertainty. Do not scale until actual incremental contribution after new lease charges and matched controls supports expansion. July is a short evaluation window, not a promised payback period.',
            control_definition=f'Preassign {controls[0]}: {control_description}, different bank, left unchanged. Compare June baseline with July 15-30 using changes relative to this control; track other-bank switching. Retain machine-level daily meters and settings. Extend follow-up before a fleet-wide decision.',
            limitation='Game mix may explain the gap. A different title is unobserved; one treated machine per zone and 16 days have low power. Peer earnings include payout variation and player switching. July net scenario can be negative; information value and longer-term gains are unpriced.',
            expected_uplift_usd_per_day=dollars(daily*.5),low_uplift_usd_per_day='0',high_uplift_usd_per_day=dollars(daily),
            downtime_opportunity_cost_usd_per_hour=dollars(opportunity),additional_comp_cost_usd='0'))
        evidence.append(dict(machine=mid,control=controls[0],actual_rate=actual['actual_rate'],peer_rate=actual['peer_rate'],gap=gap))
    leads=records(con,'''SELECT s.* FROM marts.mart_machine_scorecard s JOIN marts.mart_machine_daily d
        ON d.machine_id=s.machine_id AND d.gaming_date=(SELECT max(gaming_date) FROM marts.mart_machine_daily)
        WHERE s.hold_anomaly_flag AND s.luck_residual_usd<0 ORDER BY s.luck_q_value,s.machine_id LIMIT 1''')
    if not leads:
        raise ValueError('No current payout-inspection lead; revise the proposal instead of inventing one.')
    lead=leads[0]
    proposals.append(dict(proposal_line_id='JUL-INSPECT-01',action_type_id='A-INSPECT',target_type='machine',
        target_id=lead['machine_id'],selected='true',quantity=1,
        effect_assumption=f'Verify the configured paytable, meter reconciliation and software/configuration for {lead["machine_id"]}. Observed hold is {lead["observed_hold"]:.2%} versus configured expected hold {lead["expected_hold"]:.2%}; corrected payout-test q={lead["luck_q_value"]:.4f} across the declared eligible-machine family. This is an inspection lead, not proof of a fault or wrongdoing. Expected output is a signed verification and a documented fix-or-monitor decision; no revenue recovery is assumed.',
        cost_assumption='$1200 fixed inspection package with one-day lead and two-hour shutdown; no purchase or replacement ordered. Monetary recovery is not priced.',
        evidence_refs='mart_machine_scorecard;mart_machine_daily;mart_machine_month',
        measurement_metric='Complete paytable/configuration and meter audit by July 3; record observed findings, test results, availability and any approved correction. If no fault is found, continue monitoring rather than claiming recovered revenue.',
        control_definition='Compare recorded configured RTP, game-math configuration and independent meter audit; preserve pre-inspection readings and compare with unchanged same-configuration machines.',
        limitation='Statistical evidence is approximate and does not establish causation. Rare payouts can affect results; inspection may find no fault. Information value is not assigned a dollar amount.',additional_comp_cost_usd='0'))
    # Verify all ten screened machines before replacement. Only the first
    # inspection is a statistical payout lead; these ten are due diligence.
    for i,candidate in enumerate(screened,1):
        proposals.append(dict(proposal_line_id=f'JUL-PRECHECK-{i:02d}',action_type_id='A-INSPECT',
            target_type='machine',target_id=candidate['machine_id'],selected='true',quantity=1,
            effect_assumption=f'Pre-replacement configuration, meter and service inspection for {candidate["machine_id"]}. '
                f'The screened machine wagered {candidate["peer_coin_in_rate_ratio"]:.1%} of zone peers with weakness in '
                f'{candidate["persistent_months"]}/{candidate["eligible_months"]} months. This is due diligence, not a claim of a payout fault.',
            cost_assumption='$1200 inspection package; one-day lead and two-hour shutdown. Schedule July 2-3 before maintenance and July 15 replacement. Information value is unpriced.',
            evidence_refs='mart_machine_scorecard;mart_machine_daily;mart_tickets',
            measurement_metric='Complete a signed paytable, meter and service check by July 3; record whether an operational correction explains weak demand. Use findings to select the replacement title and document the replacement decision.',
            control_definition='Preserve pre-inspection readings and verify against the configured game math and independent meters. Compare with unchanged same-game machines; no inspection recovery is assumed.',
            limitation='An inspection may find no defect. Low demand can reflect game mix or location; the inspection is not proof that replacement will improve earnings.',additional_comp_cost_usd='0'))
    history_days=con.execute("SELECT date_diff('day',min(gaming_date),max(gaming_date))+1 FROM marts.mart_machine_daily").fetchone()[0]
    maintenance=records(con,'''SELECT manufacturer,
        sum(estimated_lost_theo_usd*fault_downtime_seconds/nullif(downtime_seconds,0))::DOUBLE AS fault_value,
        sum(fault_downtime_seconds)/3600.0 AS fault_hours
        FROM marts.mart_downtime_hourly WHERE fault_downtime_seconds>0 GROUP BY 1 ORDER BY fault_value DESC''')
    for i,row in enumerate(maintenance,1):
        maker=row['manufacturer']
        baseline=con.execute('SELECT sum(house_win_usd)::DOUBLE/nullif(sum(available_seconds)/3600.0,0) FROM marts.mart_machine_daily WHERE manufacturer=?',[maker]).fetchone()[0]
        current_count=con.execute('SELECT count(*) FROM marts.mart_machine_daily WHERE manufacturer=? AND gaming_date=(SELECT max(gaming_date) FROM marts.mart_machine_daily)',[maker]).fetchone()[0]
        daily=row['fault_value']/history_days
        proposals.append(dict(proposal_line_id=f'JUL-MAINT-{i:02d}',action_type_id='A-PREVENTIVE',target_type='manufacturer',target_id=maker,selected='true',quantity=1,
            effect_assumption=f'Preventive sweep for {maker}: {row["fault_hours"]:.1f} observed fault machine-hours and ${row["fault_value"]:.0f} estimated Lost Expected Value in January-June. Central scenario recovers 25% of the historical daily estimated fault loss, low 0%, high 50%; these are assumed preventable fractions, not measured treatment effects.',
            cost_assumption=f'$9000 fixed manufacturer package, seven-day lead, 90 minutes downtime per each of {current_count} current machines. Start July 8 and stagger by bank in quiet hours before July 15 replacements. Installation opportunity loss uses observed manufacturer house win/hour; fixed costs are not credited as savings.',
            evidence_refs='mart_downtime_hourly;mart_tickets;mart_machine_daily',
            measurement_metric='Record fault machine-hours per scheduled hour, repeat tickets, actual house win and contribution per available hour. Compare 28-day pre-period with July follow-up; record maintenance shutdowns separately.',
            control_definition='Stagger servicing across banks within the manufacturer so not-yet-serviced banks provide short-term comparisons. Adjust for weekday and common property events; log actual completion dates.',
            limitation='Historical lost earnings are peer-based estimates, not observed lost cash. Preventable fraction is unknown. The full-budget sweep can have negative July net value; longer-term equipment benefits are unpriced. Overlaps with inspections, replacements and promotion prevent summing causal benefits.',
            expected_uplift_usd_per_day=dollars(daily*.25),low_uplift_usd_per_day='0',high_uplift_usd_per_day=dollars(daily*.5),
            downtime_opportunity_cost_usd_per_hour=dollars(max(0,baseline)),additional_comp_cost_usd='0'))
    zone=con.execute("SELECT sum(house_win_usd)::DOUBLE, sum(coin_in_usd)::DOUBLE/nullif(sum(available_seconds)/3600.0,0) FROM marts.mart_machine_daily WHERE zone_id='Z-B40'").fetchone()
    zone_daily=max(0,zone[0])/history_days
    proposals.append(dict(proposal_line_id='JUL-SIGN-01',action_type_id='A-WAYFINDING',target_type='zone',target_id='Z-B40',selected='true',quantity=1,
        effect_assumption=f'Back Forty wayfinding and sightline refresh. The zone recorded ${zone[1]:.2f} wagered per available machine-hour over January-June. Central scenario adds 3% of its historical daily observed house win, low 0%, high 6%; response to signage is unmeasured.',
        cost_assumption='$7500 fixed zone package; ten-day lead; no catalogue machine shutdown. No construction or extra promotional rewards are included.',
        evidence_refs='mart_zone_daily;mart_machine_daily',
        measurement_metric='Track coverage-adjusted entry counts, wagering and actual contribution per available hour before and after July 11. Record whether higher entries convert to machine use.',
        control_definition='Compare changes with other zones and the pre-period weekday pattern. Inspect machine-level effects separately from July 15 replacement changes; record the property-wide promotion as a common event.',
        limitation='Zone entries are crossings, not unique guests. Signage may only redistribute play; game mix and overlapping replacements confound the result. Scenario income is not a causal or net floor-loss estimate.',
        expected_uplift_usd_per_day=dollars(zone_daily*.03),low_uplift_usd_per_day='0',high_uplift_usd_per_day=dollars(zone_daily*.06),additional_comp_cost_usd='0'))
    proposals.append(dict(proposal_line_id='JUL-SURVEY-01',action_type_id='A-SURVEY',target_type='property',target_id='property',selected='true',quantity=1,
        effect_assumption='Expand the casino guest intercept survey to test why screened machines receive weak wagering: game/title preference, location visibility, availability and reward experience. Expected output is a zone- and time-stratified preference/visibility analysis; no revenue uplift is assumed.',
        cost_assumption='$3500 catalogue package for one month; seven-day lead. The catalogue triples the existing monthly sample; do not invent a sample count not specified by the release.',
        evidence_refs='mart_machine_scorecard;mart_zone_daily;mart_player_month',
        measurement_metric='From July 8, record refusal rate, sampling time and zone, machine-title preferences and awareness of Back Forty. Report segment sample sizes and uncertainty; include both carded and uncarded visitors.',
        control_definition='Use the existing survey instrument as a comparison, add identical core questions and stratify collection by zone, shift and weekday. Keep survey participation unrelated to gambling spend.',
        limitation='Survey responses are self-reported and may be selectively sampled. Survey information has no assigned dollar benefit and cannot by itself prove replacement value.',additional_comp_cost_usd='0'))
    forecast=con.execute("SELECT avg(model_prediction_usd)::DOUBLE FROM marts.mart_forecast WHERE forecast_date BETWEEN '2025-07-18' AND '2025-07-20'").fetchone()[0]
    actual_hold=con.execute('SELECT sum(house_win_usd)::DOUBLE/nullif(sum(coin_in_usd),0) FROM marts.mart_machine_daily').fetchone()[0]
    daily_expected=forecast*max(0,actual_hold)
    proposals.append(dict(proposal_line_id='JUL-EVENT-01',action_type_id='A-PROMO',target_type='property',target_id='property',selected='true',quantity=1,
        effect_assumption='One general property promotion weekend July 18-20, after the 14-day lead. Central scenario assumes 2% incremental wagering relative to the saved no-action forecast, low 0%, high 5%, converted to earnings using the observed January-June house-win/wager ratio. No uplift is inferred from the forecast itself.',
        cost_assumption='$15000 fixed package covering marketing, prizes and staffing for one three-day weekend. No additional compensation outside the package; no campaign targeted at heavy losers.',
        evidence_refs='mart_forecast;mart_floor_daily;mart_player_month',
        measurement_metric='Track incremental actual wagering and supplied-cost contribution against matched prior weekdays and forecast, plus realized payout variation, promotional cost and protective player-outcome guardrails. Do not interpret house-win noise as proven campaign return.',
        control_definition='Preassign an eligible audience holdout before July 18 and measure intention-to-treat visit response; use July 25-27 only as an additional calendar comparison. Log promotion eligibility separately from loyalty or loss status.',
        limitation='A randomized audience holdout requires new assignment logs. The assumed wagering lift and observed historical hold do not establish causal profit. Players may substitute visits across days, and other funded actions overlap.',
        expected_uplift_usd_per_day=dollars(daily_expected*.02),low_uplift_usd_per_day='0',high_uplift_usd_per_day=dollars(daily_expected*.05),
        benefit_days_per_unit='3',additional_comp_cost_usd='0',forecast_allocation_share='1',unit_start_dates='2025-07-18'))
    return proposals,evidence,lead


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'output/casino.duckdb')
    parser.add_argument('--output',type=Path,default=ROOT/'config/action_proposals.csv')
    args=parser.parse_args()
    with duckdb.connect(str(args.database),read_only=True) as con:
        proposals,evidence,lead=generate(con)
        catalogue={r['action_type_id']:r for r in records(con,'SELECT * FROM metadata.action_catalog')}
        current=records(con,'SELECT machine_id,zone_id,bank_id,manufacturer FROM marts.mart_machine_daily WHERE gaming_date=(SELECT max(gaming_date) FROM marts.mart_machine_daily)')
        forecast=dict(con.execute("SELECT forecast_date,model_prediction_usd FROM marts.mart_forecast WHERE split='future'").fetchall())
        prepared=[]
        targets={}
        fields={'machine':'machine_id','zone':'zone_id','bank':'bank_id','manufacturer':'manufacturer'}
        for row in proposals:
            target_set={r['machine_id'] for r in current if row['target_type']=='property' or r[fields[row['target_type']]]==row['target_id']}
            if not target_set:
                raise ValueError('Inactive or missing proposal target: '+row['target_id'])
            targets[row['proposal_line_id']]=target_set
            prepared.append(prepare_proposal(row,catalogue[row['action_type_id']],target_set,forecast))
        validate_portfolio(prepared,catalogue,targets)
        if sum(r['total_cost_usd'] for r in prepared)!=Decimal('100000.00'):
            raise ValueError('The full-budget portfolio must allocate exactly $100000.')
    with args.output.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,FIELDS);writer.writeheader();writer.writerows(proposals)
    report=['# Full-budget July action portfolio','',
        'Working plan: spend exactly $100,000 with no action-type cap, as requested. Catalogue quantity limits and target conflicts remain enforced. The official competition guide has a three-action-type submission rule; this six-type working plan needs consolidation if that rule is enforced at submission.','',
        '| Action | Units | Cash cost |','| --- | ---: | ---: |',
        '| Leased replacements for screened machines | 10 | $33,800 |',
        '| Inspections: ten screened machines plus payout lead | 11 | $13,200 |',
        '| Manufacturer preventive sweeps | 3 | $27,000 |',
        '| Back Forty signage | 1 | $7,500 |',
        '| Expanded guest survey | 1 | $3,500 |',
        '| July 18-20 property promotion | 1 | $15,000 |',
        '| Total | | $100,000 |','',
        '| Replacement | Unchanged control | Actual earnings / hr | Zone peers / hr | Observed gap / hr |',
        '| --- | --- | ---: | ---: | ---: |']
    for row in evidence:
        report.append(f"| {row['machine']} | {row['control']} | ${row['actual_rate']:.2f} | ${row['peer_rate']:.2f} | ${row['gap']:.2f} |")
    report+=['',f"Payout inspection lead: {lead['machine_id']}, observed hold {lead['observed_hold']:.2%}, configured expected hold {lead['expected_hold']:.2%}, adjusted q={lead['luck_q_value']:.4f}. The other ten inspections are due diligence, not ten additional payout-anomaly claims.",'',
        'All effects are explicit scenarios or unpriced information outcomes. Full budget allocation is a user constraint, not an assertion that each action maximizes July return. July scenarios can be negative. Overlapping actions and imperfect controls mean benefits are not independently additive.','',
        'Every row contains timing, target, costs, evidence, controls, measurement and limitations. Inspection and survey information benefits remain unknown rather than zero.','']
    (ROOT/'docs/action_evidence.md').write_text('\n'.join(report),encoding='utf-8')
    print(f'Wrote {len(proposals)} proposal lines; 6 action types, $100000 cash allocation.')


if __name__=='__main__':
    main()
