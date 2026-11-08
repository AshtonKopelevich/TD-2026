"""Stage six: approximate luck tests, paired block sensitivity, descriptive evidence."""

from collections import defaultdict
from datetime import timedelta
import hashlib
import math
from pathlib import Path

import numpy as np

from .. import constants as c
from ..descriptive import MartContract, MONTH, MACHINE_SUMS, RATIOS, check_query, validate_contract


DETAIL_COLUMNS = {
    **dict.fromkeys("positive_wager_days bootstrap_usable_blocks bootstrap_covered_days bootstrap_valid_replicates bootstrap_replicates test_family_size".split(), "BIGINT"),
    "clt_eligible": "BOOLEAN", "bootstrap_eligible": "BOOLEAN",
    **dict.fromkeys("clt_status bootstrap_status statistical_family".split(), "VARCHAR"),
}
MONTH_STATS = MartContract(MONTH.name,MONTH.key,{**MONTH.columns,**DETAIL_COLUMNS},MONTH.nullable)
SCORECARD = MartContract("mart_machine_scorecard", ("machine_id",), {
    "machine_id": "VARCHAR", "analysis_start": "DATE", "analysis_end": "DATE", "active_days": "BIGINT",
    **{name: MONTH.columns[name] for name in MACHINE_SUMS}, **dict.fromkeys(RATIOS,"DOUBLE"),
    "outcome_variance_usd2": "DOUBLE",
    **dict.fromkeys("naive_rank adjusted_rank peer_coverage_days".split(),"BIGINT"), "naive_bottom_10": "BOOLEAN",
    **dict.fromkeys("peer_theo_per_hour peer_rate_ratio peer_coin_in_per_hour peer_coin_in_rate_ratio peer_expected_contribution_per_hour floor_coin_in_per_hour zone_to_floor_coin_ratio peer_coverage_fraction".split(),"DOUBLE"),
    **dict.fromkeys("luck_z_score luck_p_value luck_q_value bootstrap_hold_gap_low bootstrap_hold_gap_high".split(),"DOUBLE"),
    **DETAIL_COLUMNS,"statistical_status": "VARCHAR",
    **dict.fromkeys("weak_demand_flag location_flag downtime_flag repair_rebound_flag hold_anomaly_flag luck_compatible".split(),"BOOLEAN"),
    "primary_classification": "VARCHAR", "classification_reason": "VARCHAR",
    "dependence_warning": "BOOLEAN", "exposure_concentration_warning": "BOOLEAN", "method_disagreement": "BOOLEAN",
    "eligible_fault_tickets": "BIGINT", "rebound_fault_tickets": "BIGINT", "repair_evidence_status": "VARCHAR",
}, frozenset(RATIOS + tuple("peer_theo_per_hour peer_rate_ratio peer_coin_in_per_hour peer_coin_in_rate_ratio peer_expected_contribution_per_hour floor_coin_in_per_hour zone_to_floor_coin_ratio peer_coverage_fraction luck_z_score luck_p_value luck_q_value bootstrap_hold_gap_low bootstrap_hold_gap_high weak_demand_flag location_flag downtime_flag repair_rebound_flag hold_anomaly_flag luck_compatible dependence_warning".split())))
CONTRACTS = (SCORECARD, MONTH_STATS)


def benjamini_hochberg(pvalues):
    """Return adjusted values in input order, for finite probabilities."""
    if any(not math.isfinite(p) or not 0<=p<=1 for p in pvalues):
        raise ValueError("BH requires finite p-values in [0,1]")
    order = sorted(range(len(pvalues)),key=lambda i:(pvalues[i],i))
    result = [None]*len(pvalues)
    previous = 1.0
    for rank in range(len(pvalues),0,-1):
        index = order[rank-1]
        # Preserve q >= p even at a floating-point rounding boundary.
        previous = max(pvalues[index],min(previous,pvalues[index]*(len(pvalues)/rank)))
        result[index] = previous
    return result


def paired_blocks(rows,block_days):
    """Complete nonoverlapping weeks within contiguous placement episodes.

    Rows: (date, placement_id, residual dollars, coin-in dollars, variance, ...).
    Remainders are not concatenated across gaps or placements.
    """
    episodes = []
    for row in rows:
        if (not episodes or row[1]!=episodes[-1][-1][1]
                or row[0]-episodes[-1][-1][0]!=timedelta(days=1)):
            episodes.append([])
        episodes[-1].append(row)
    strata = []
    for episode in episodes:
        blocks = []
        for start in range(0,len(episode)-block_days+1,block_days):
            part = episode[start:start+block_days]
            blocks.append((sum(float(r[2]) for r in part),sum(float(r[3]) for r in part)))
        if blocks:
            strata.append(np.asarray(blocks,dtype=float))
    return strata


def block_interval(rows,key,min_active,min_positive):
    strata = paired_blocks(rows,c.BOOTSTRAP_BLOCK_DAYS)
    blocks = sum(len(s) for s in strata)
    covered = blocks*c.BOOTSTRAP_BLOCK_DAYS
    base = dict(bootstrap_usable_blocks=blocks,bootstrap_covered_days=covered,
                bootstrap_valid_replicates=0,bootstrap_replicates=0,bootstrap_eligible=False,
                bootstrap_hold_gap_low=None,bootstrap_hold_gap_high=None)
    if len(rows)<min_active or sum(float(r[3])>0 for r in rows)<min_positive:
        return {**base,"bootstrap_status":"insufficient_exposure"}
    if blocks<c.MIN_USABLE_BOOTSTRAP_BLOCKS:
        return {**base,"bootstrap_status":"insufficient_blocks"}
    if covered/len(rows)<c.MIN_BOOTSTRAP_COVERAGE_FRACTION:
        return {**base,"bootstrap_status":"insufficient_block_coverage"}
    seed = int.from_bytes(hashlib.blake2b(f"{c.RANDOM_SEED}:{key}".encode(),digest_size=8).digest(),'big')
    rng = np.random.default_rng(seed)
    ratios = []
    for start in range(0,c.BOOTSTRAP_REPLICATES,512):
        size = min(512,c.BOOTSTRAP_REPLICATES-start)
        residual,coin = np.zeros(size),np.zeros(size)
        for stratum in strata:
            sampled = stratum[rng.integers(0,len(stratum),size=(size,len(stratum)))]
            residual += sampled[:,:,0].sum(axis=1)
            coin += sampled[:,:,1].sum(axis=1)
        ratios.extend((residual[coin>0]/coin[coin>0]).tolist())
    base.update(bootstrap_eligible=True,bootstrap_replicates=c.BOOTSTRAP_REPLICATES,
                bootstrap_valid_replicates=len(ratios))
    if len(ratios)<c.BOOTSTRAP_REPLICATES*c.MIN_BOOTSTRAP_VALID_FRACTION:
        return {**base,"bootstrap_status":"insufficient_valid_resamples"}
    if np.ptp(ratios)<=1e-15:
        return {**base,"bootstrap_status":"degenerate_blocks"}
    low,high = np.quantile(ratios,[c.ALPHA/2,1-c.ALPHA/2])
    return {**base,"bootstrap_status":"available","bootstrap_hold_gap_low":float(low),"bootstrap_hold_gap_high":float(high)}


def period_statistics(rows,machine_id,period):
    monthly = period!="full"
    min_active = c.MONTH_MIN_ACTIVE_DAYS if monthly else c.MIN_ACTIVE_DAYS
    min_positive = c.MONTH_MIN_POSITIVE_WAGER_DAYS if monthly else c.MIN_POSITIVE_WAGER_DAYS
    npositive = sum(float(r[3])>0 for r in rows)
    variance = sum(float(r[4]) for r in rows)
    residual = sum(float(r[2]) for r in rows)
    status = ("insufficient_active_days" if len(rows)<min_active else
              "insufficient_positive_wager_days" if npositive<min_positive else
              "zero_variance" if variance<=0 else "eligible")
    eligible = status=="eligible"
    z = residual/math.sqrt(variance) if eligible else None
    result = dict(machine_id=machine_id,period=period,positive_wager_days=npositive,
        active_days=len(rows),outcome_variance_usd2=variance,
        clt_eligible=eligible,clt_status=status,luck_z_score=z,
        luck_p_value=math.erfc(abs(z)/math.sqrt(2)) if z is not None else None,
        luck_q_value=None,statistical_family="full_window" if not monthly else "month:"+period,test_family_size=0)
    result.update(block_interval(rows,machine_id+":"+period,min_active,min_positive))
    result["statistical_status"] = ("clt_and_block_bootstrap" if eligible and result["bootstrap_status"]=="available"
        else "clt_only" if eligible else "bootstrap_only" if result["bootstrap_status"]=="available" else "insufficient_evidence")
    return result


def correlation(x,y):
    pairs = [(a,b) for a,b in zip(x,y) if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    if len(pairs)<c.MIN_DEPENDENCE_PAIRS:
        return None
    a,b = np.asarray(pairs,dtype=float).T
    if np.ptp(a)==0 or np.ptp(b)==0:
        return None
    result = float(np.corrcoef(a,b)[0,1])
    return result if math.isfinite(result) else None


def dependence_diagnostics(rows,machine_id,period):
    scaled = [float(r[2])/math.sqrt(float(r[4])) if float(r[4])>0 else None for r in rows]
    previous = [scaled[i-1] if i>0 and rows[i][1]==rows[i-1][1]
        and rows[i][0]-rows[i-1][0]==timedelta(days=1) else None for i in range(len(rows))]
    factors = {"lag1":previous,"weekend":[float(r[0].weekday()>=5) for r in rows],
               "day_of_month":[float(r[0].day) for r in rows],
               "temperature":[float(r[5]) if r[5] is not None else None for r in rows],
               "traffic":[float(r[6]) if r[6] is not None else None for r in rows],
               "events":[float(r[7]) for r in rows]}
    corrs = {name:correlation(scaled,values) for name,values in factors.items()}
    observed = [abs(v) for v in corrs.values() if v is not None]
    variance,coin = sum(float(r[4]) for r in rows),sum(float(r[3]) for r in rows)
    return {"machine_id":machine_id,"period":period,**corrs,
            "dependence_warning":max(observed)>=c.DEPENDENCE_WARNING_CORRELATION if observed else None,
            "max_day_variance_share":max(float(r[4]) for r in rows)/variance if variance>0 else None,
            "max_day_wager_share":max(float(r[3]) for r in rows)/coin if coin>0 else None}


def classify(flags,eligible,luck_compatible,negative_bottom,warning,disagreement):
    positives = [name for name,value in flags.items() if value is True]
    if not eligible:
        return "insufficient_evidence","Insufficient full-window operating exposure; unavailable flags remain NULL."
    if disagreement or warning:
        return ("mixed_evidence" if positives or disagreement else "insufficient_evidence",
                "Statistical diagnostics disagree or show residual dependence/concentrated exposure; inspect component evidence.")
    if len(positives)>1:
        return "mixed_evidence","Overlapping descriptive evidence: "+", ".join(positives)+"."
    labels = {"weak_demand_flag":"weak_demand_candidate","location_flag":"location_associated",
              "downtime_flag":"downtime_associated","repair_rebound_flag":"repair_associated",
              "hold_anomaly_flag":"hold_inspection_lead"}
    if positives:
        return labels[positives[0]],"Descriptive evidence: "+positives[0]+"; this is not a causal or replacement verdict."
    if luck_compatible and negative_bottom:
        return "luck_compatible","Low raw earnings with a negative residual compatible with tested luck variation; not proof of normal operation."
    if all(value is None for value in flags.values()):
        return "insufficient_evidence","No eligible component evidence."
    return "no_clear_issue","No configured evidence trigger; this does not establish that every possible issue is absent."


def build_machines(con):
    if not 0<c.ALPHA<1 or min(c.BOOTSTRAP_BLOCK_DAYS,c.BOOTSTRAP_REPLICATES,c.MIN_USABLE_BOOTSTRAP_BLOCKS)<=0:
        raise ValueError("Invalid machine statistics settings")
    root = Path(__file__).resolve().parents[3]/"sql"
    con.execute((root/"staging"/"machine_daily.sql").read_text(encoding="utf-8"))
    observations = con.execute("""SELECT d.machine_id,d.gaming_date,p.placement_id,d.luck_residual_usd,
        d.coin_in_usd,d.outcome_variance_usd2,f.weather_temperature_max_c,
        CASE WHEN z.counter_coverage_ratio>=0.8 THEN z.entries_observed END AS traffic,
        f.events_active IS NOT NULL AS has_event
        FROM marts.mart_machine_daily d JOIN raw.calendar_day c USING(gaming_date)
        JOIN raw.placements p ON p.machine_id=d.machine_id AND p.effective_from_utc<c.gaming_day_end_utc
          AND coalesce(p.effective_to_utc,TIMESTAMP '9999-12-31')>c.gaming_day_start_utc
        LEFT JOIN marts.mart_floor_daily f USING(gaming_date)
        LEFT JOIN marts.mart_zone_daily z ON z.zone_id=d.zone_id AND z.gaming_date=d.gaming_date
        ORDER BY d.machine_id,d.gaming_date""").fetchall()
    groups = defaultdict(list)
    for machine_id,*row in observations:
        groups[machine_id,"full"].append(row)
        groups[machine_id,row[0].strftime('%Y-%m')].append(row)
    results = [period_statistics(rows,*key) for key,rows in groups.items()]
    families = defaultdict(list)
    for result in results:
        if result["luck_p_value"] is not None:
            families[result["statistical_family"]].append(result)
    for family in families.values():
        qvalues = benjamini_hochberg([r["luck_p_value"] for r in family])
        for result,qvalue in zip(family,qvalues):
            result.update(luck_q_value=qvalue,test_family_size=len(family))
    for result in results:
        result["test_family_size"] = len(families[result["statistical_family"]])
    fields = {"machine_id":"VARCHAR","period":"VARCHAR",**DETAIL_COLUMNS,
        "active_days":"BIGINT","outcome_variance_usd2":"DOUBLE",
        **dict.fromkeys("luck_z_score luck_p_value luck_q_value bootstrap_hold_gap_low bootstrap_hold_gap_high".split(),"DOUBLE"),
        "statistical_status":"VARCHAR"}
    con.execute("CREATE TABLE diagnostics.machine_statistics ("+",".join(f'{k} {v}' for k,v in fields.items())+")")
    con.executemany("INSERT INTO diagnostics.machine_statistics VALUES ("+",".join("?" for _ in fields)+")",
                    [[r[k] for k in fields] for r in results])
    diagnostics = [dependence_diagnostics(rows,*key) for key,rows in groups.items()]
    corr_names = ("lag1","weekend","day_of_month","temperature","traffic","events")
    diag_fields = {"machine_id":"VARCHAR","period":"VARCHAR",**dict.fromkeys(corr_names,"DOUBLE"),
                   "dependence_warning":"BOOLEAN","max_day_variance_share":"DOUBLE","max_day_wager_share":"DOUBLE"}
    con.execute("CREATE TABLE diagnostics.machine_dependence ("+",".join(f'{k} {v}' for k,v in diag_fields.items())+")")
    con.executemany("INSERT INTO diagnostics.machine_dependence VALUES ("+",".join("?" for _ in diag_fields)+")",
                    [[r[k] for k in diag_fields] for r in diagnostics])
    for name,dtype in DETAIL_COLUMNS.items():
        con.execute(f'ALTER TABLE marts.mart_machine_month ADD COLUMN "{name}" {dtype}')
    update_fields = tuple(DETAIL_COLUMNS)+("luck_z_score","luck_p_value","luck_q_value","bootstrap_hold_gap_low","bootstrap_hold_gap_high","statistical_status")
    con.execute("UPDATE marts.mart_machine_month m SET "+",".join(f'"{name}"=s."{name}"' for name in update_fields)+
        " FROM diagnostics.machine_statistics s WHERE s.machine_id=m.machine_id AND s.period=strftime(m.month_start,'%Y-%m')")
    replacements = {"{{min_active}}":c.MIN_ACTIVE_DAYS,"{{min_positive}}":c.MIN_POSITIVE_WAGER_DAYS,
        "{{min_peers}}":c.MIN_DAILY_MACHINE_PEERS,"{{min_coverage_days}}":c.MIN_PEER_COVERAGE_DAYS,
        "{{min_coverage_fraction}}":c.MIN_PEER_COVERAGE_FRACTION,"{{weak_gap}}":c.WEAK_DEMAND_RELATIVE_GAP,
        "{{downtime_share}}":c.DOWNTIME_SHARE_TRIGGER,"{{alpha}}":c.ALPHA,
        "{{variance_warning}}":c.MAX_SINGLE_DAY_VARIANCE_SHARE,"{{wager_warning}}":c.MAX_SINGLE_DAY_WAGER_SHARE,
        "{{min_fault_tickets}}":c.MIN_COMPARABLE_FAULT_TICKETS,"{{rebound_gap}}":c.REPAIR_REBOUND_MIN_RELATIVE_CHANGE,
        "{{rebound_share}}":c.REPAIR_REBOUND_MIN_SHARE}
    replacements["{{sum_measures}}"] = ",\n".join(
        f'sum(d."{name}")::{MONTH.columns[name]} AS "{name}"' for name in MACHINE_SUMS)
    sql = (root/"marts"/"machine_scorecard.sql").read_text(encoding="utf-8")
    for key,value in replacements.items():
        sql = sql.replace(key,"NULL" if value is None else str(value))
    con.execute(sql)
    rows = con.execute("""SELECT machine_id,active_days,weak_demand_flag,location_flag,downtime_flag,
        repair_rebound_flag,hold_anomaly_flag,luck_compatible,naive_bottom_10 AND luck_residual_usd<0,
        coalesce(dependence_warning,false) OR exposure_concentration_warning,method_disagreement
        FROM marts.mart_machine_scorecard""").fetchall()
    updates = []
    names = ("weak_demand_flag","location_flag","downtime_flag","repair_rebound_flag","hold_anomaly_flag")
    for machine_id,days,*values in rows:
        label,reason = classify(dict(zip(names,values[:5])),days>=c.MIN_ACTIVE_DAYS,*values[5:])
        updates.append((label,reason,machine_id))
    con.executemany("UPDATE marts.mart_machine_scorecard SET primary_classification=?,classification_reason=? WHERE machine_id=?",updates)


def validate_machines(con):
    checks = [check for contract in CONTRACTS for check in validate_contract(con,contract)]
    queries = {
        "coverage": """SELECT abs((SELECT count(*) FROM marts.mart_machine_scorecard)-
          (SELECT count(DISTINCT machine_id) FROM marts.mart_machine_daily))""",
        "probabilities": """SELECT count(*) FROM diagnostics.machine_statistics WHERE
          luck_p_value NOT BETWEEN 0 AND 1 OR luck_q_value NOT BETWEEN 0 AND 1
          OR luck_q_value<luck_p_value OR (NOT clt_eligible AND (luck_p_value IS NOT NULL OR luck_q_value IS NOT NULL))
          OR bootstrap_hold_gap_low>bootstrap_hold_gap_high OR bootstrap_valid_replicates>bootstrap_replicates""",
        "rankings": """SELECT count(*) FROM (
          SELECT machine_id,naive_rank,adjusted_rank,naive_bottom_10,
            row_number() OVER(ORDER BY house_win_usd,machine_id) AS n,
            row_number() OVER(ORDER BY expected_contribution_per_available_hour ASC NULLS LAST,machine_id) AS a
          FROM marts.mart_machine_scorecard) WHERE naive_rank<>n OR adjusted_rank<>a OR naive_bottom_10 IS DISTINCT FROM (n<=10)""",
        "money_reconciliation": """WITH daily AS (SELECT machine_id,sum(theo_usd) AS theo,sum(house_win_usd) AS win,
          sum(machine_cost_usd) AS cost,sum(available_seconds) AS seconds FROM marts.mart_machine_daily GROUP BY machine_id)
          SELECT count(*) FROM marts.mart_machine_scorecard s JOIN daily d USING(machine_id)
          WHERE s.theo_usd<>d.theo OR s.house_win_usd<>d.win OR s.machine_cost_usd<>d.cost OR s.available_seconds<>d.seconds""",
        "inspection_eligibility": """SELECT count(*) FROM marts.mart_machine_scorecard WHERE
          hold_anomaly_flag AND NOT clt_eligible OR primary_classification IS NULL OR classification_reason IS NULL""",
    }
    checks.extend(check_query(con,"machine_scorecard."+name,sql) for name,sql in queries.items())
    return checks
