"""Stage-four guest/comp contracts and orchestration.

Financial facts are aggregated independently before joining. Event time, not
feed-arrival time, defines loyalty and POS gaming dates.
"""

from pathlib import Path

from . import constants
from .descriptive import MartContract, check_query, validate_contract
from .machine_daily import MONEY, THEO
from .analysis.players import build_player_diagnostics


ECONOMIC_MONEY = tuple("tracked_coin_in_usd tracked_payout_usd actual_tracked_loss_usd linked_pos_cash_usd linked_pos_cogs_usd total_tracked_spend_usd comp_face_value_usd comp_cost_usd tracked_contribution_usd".split())
POINTS = tuple("points_earned points_redeemed points_balance_start points_balance_end points_balance_change".split())
COMP_RATIOS = tuple("comp_cost_per_actual_loss comp_cost_per_total_spend comp_cost_per_coin_in theo_per_comp_cost".split())
ECONOMICS = {**dict.fromkeys(ECONOMIC_MONEY, MONEY), "tracked_theo_usd": THEO,
             **dict.fromkeys(POINTS, "BIGINT"), **dict.fromkeys(COMP_RATIOS, "DOUBLE"),
             "actual_loss_ratio_status": "VARCHAR", "total_spend_ratio_status": "VARCHAR"}
PLAYER_MONEY = tuple("tracked_coin_in_usd tracked_payout_usd tracked_net_usd actual_tracked_loss_usd linked_pos_cash_usd linked_pos_cogs_usd comp_face_value_usd comp_cost_usd tracked_contribution_usd".split())
PLAYER_COUNTS = tuple("observed_visits incomplete_visits sessions comps_redeemed points_earned points_redeemed".split())
PLAYER = MartContract("mart_player_month", ("player_id", "month_start"), {
    "player_id": "VARCHAR", "month_start": "DATE",
    **dict.fromkeys("home_region age_band opening_tier tier_end".split(), "VARCHAR"),
    **dict.fromkeys(PLAYER_COUNTS, "BIGINT"), "carded_play_hours": "DOUBLE",
    **dict.fromkeys(PLAYER_MONEY, MONEY), "theo_usd": THEO, "luck_residual_usd": THEO,
    "winner_flag": "BOOLEAN", "above_expected_loss_flag": "BOOLEAN", "protective_status": "VARCHAR",
}, frozenset({"above_expected_loss_flag"}))
VISITS = MartContract("mart_visits_month", ("month_start", "home_region", "age_band", "opening_tier"), {
    "month_start": "DATE", **dict.fromkeys("home_region age_band opening_tier".split(), "VARCHAR"),
    **dict.fromkeys("observed_visits complete_visits incomplete_visits visits_with_gaming complete_gaming_visits winning_visits unique_players".split(), "BIGINT"),
    **dict.fromkeys("visit_assigned_coin_in_usd visit_assigned_payout_usd visit_assigned_player_net_usd visit_assigned_pos_cash_usd".split(), MONEY),
    "visit_assigned_theo_usd": THEO, "coin_in_per_visit": "DOUBLE", "winner_share_complete_visits": "DOUBLE",
}, frozenset({"winner_share_complete_visits"}))
COMPS_DAILY = MartContract("mart_comps_daily", ("gaming_date",), {
    "gaming_date": "DATE", "month_start": "DATE", **ECONOMICS, "active_players": "BIGINT",
    "policy_change_candidate": "BOOLEAN", "change_method": "VARCHAR", "change_status": "VARCHAR",
}, frozenset(COMP_RATIOS + ("policy_change_candidate",)))
COMPS_TIER = MartContract("mart_comps_tier_month", ("opening_tier", "month_start"), {
    "opening_tier": "VARCHAR", "month_start": "DATE", "cohort_players": "BIGINT", "active_players": "BIGINT",
    **ECONOMICS, "policy_change_candidate": "BOOLEAN", "comparison_status": "VARCHAR",
}, frozenset(COMP_RATIOS + ("policy_change_candidate",)))
CONTRACTS = (PLAYER, VISITS, COMPS_DAILY, COMPS_TIER)


def validate_guest_inputs(con):
    checks = []

    def check(name, query):
        checks.append(check_query(con, "guests." + name, query))

    check("whole_month_single_year_window", """SELECT count(*) FROM staging.analysis_window
        WHERE start_date<>date_trunc('month',start_date)::DATE OR end_date<>last_day(end_date)
          OR year(start_date)<>year(end_date)""")
    for table in ("sessions", "trips", "loyalty_ledger", "player_period"):
        check(table + ".players", f"""SELECT count(*) FROM raw.{table} a LEFT JOIN raw.players p USING(player_id)
            WHERE a.player_id IS NULL OR p.player_id IS NULL""")
    check("pos.players", """SELECT count(*) FROM raw.fnb_transactions a LEFT JOIN raw.players p USING(player_id)
        WHERE a.player_id IS NOT NULL AND p.player_id IS NULL""")
    for table in ("sessions", "fnb_transactions"):
        check(table + ".visit_identity", f"""SELECT count(*) FROM raw.{table} a
            LEFT JOIN raw.trips t USING(observed_visit_id)
            WHERE (a.observed_visit_id IS NOT NULL AND
                  (t.observed_visit_id IS NULL OR a.player_id IS DISTINCT FROM t.player_id))
            {'OR a.observed_visit_id IS NULL' if table == 'sessions' else ''}""")
    check("ledger.events", """SELECT count(*) FROM raw.loyalty_ledger WHERE event_at_utc IS NULL
        OR event_type IS NULL OR event_type NOT IN ('award','redeem') OR points_delta IS NULL
        OR (event_type='award' AND points_delta<0) OR (event_type='redeem' AND points_delta>0)
        OR economic_cost_cents IS NULL OR economic_cost_cents<0 OR face_value_cents IS NULL OR face_value_cents<0
        OR (event_type='award' AND (economic_cost_cents<>0 OR face_value_cents<>0))""")
    check("ledger.redemption_links", """SELECT count(*) FROM raw.loyalty_ledger l
        LEFT JOIN raw.fnb_transactions p ON l.redeemed_pos_id=p.transaction_id
        WHERE l.event_type='redeem' AND (p.transaction_id IS NULL
            OR p.comp_id IS DISTINCT FROM l.loyalty_event_id OR p.player_id IS DISTINCT FROM l.player_id
            OR p.cogs_cents IS DISTINCT FROM l.economic_cost_cents
            OR p.face_value_cents IS DISTINCT FROM l.face_value_cents
            OR p.event_at_utc IS DISTINCT FROM l.event_at_utc)""")
    check("pos.redemption_links", """SELECT count(*) FROM raw.fnb_transactions p
        LEFT JOIN raw.loyalty_ledger l ON p.comp_id=l.loyalty_event_id
        WHERE p.comp_id IS NOT NULL AND (l.loyalty_event_id IS NULL OR l.event_type<>'redeem'
            OR l.redeemed_pos_id IS DISTINCT FROM p.transaction_id)""")
    check("ledger.unique_redeemed_receipts", """SELECT count(*) FROM (
        SELECT redeemed_pos_id FROM raw.loyalty_ledger WHERE event_type='redeem'
        GROUP BY redeemed_pos_id HAVING count(*)>1)""")
    check("source_values", """SELECT
        (SELECT count(*) FROM raw.sessions WHERE start_utc IS NULL OR end_utc IS NULL OR end_utc<start_utc
          OR gaming_date IS NULL OR coin_in_cents IS NULL OR payout_cents IS NULL OR theo_cents IS NULL
          OR coin_in_cents<0 OR payout_cents<0 OR theo_cents<0) +
        (SELECT count(*) FROM raw.fnb_transactions WHERE event_at_utc IS NULL
          OR cash_receipt_cents IS NULL OR cogs_cents IS NULL OR cash_receipt_cents<0 OR cogs_cents<0) +
        (SELECT count(*) FROM raw.trips WHERE first_observed_at_utc IS NULL OR observation_complete IS NULL) +
        (SELECT count(*) FROM raw.players WHERE enrolled_at_utc IS NULL) +
        (SELECT count(*) FROM raw.player_period WHERE NOT regexp_full_match(period_month,'[0-9]{4}-[0-9]{2}')
          OR try_cast(period_month||'-01' AS DATE) IS NULL OR period_month IS NULL)""")
    return checks


def build_guests(con):
    root = Path(__file__).resolve().parents[2] / "sql"
    timezone = constants.LOCAL_TIMEZONE.replace("'", "''")
    offset = int(constants.GAMING_DAY_START_HOUR)
    if not 0 <= offset <= 23:
        raise ValueError("Gaming-day start hour must be between 0 and 23")
    con.execute(f"""CREATE MACRO staging.gaming_date(ts) AS
        cast((ts AT TIME ZONE 'UTC' AT TIME ZONE '{timezone}') - INTERVAL '{offset} hours' AS DATE)""")
    con.execute("CREATE TABLE staging.guest_settings AS SELECT ?::VARCHAR AS protective_status, ?::VARCHAR AS change_method, ?::VARCHAR AS change_status", [
        "not_configured" if constants.PROTECTIVE_LOSS_THRESHOLD is None else "not_implemented",
        constants.COMP_CHANGE_METHOD or "not_configured",
        "not_configured" if constants.COMP_CHANGE_METHOD is None else "not_implemented"])
    for name in ("player_activity", "receipts", "loyalty", "guest_activity"):
        con.execute((root / "staging" / (name + ".sql")).read_text(encoding="utf-8"))
    for contract in CONTRACTS:
        con.execute((root / "marts" / (contract.name.removeprefix("mart_") + ".sql")).read_text(encoding="utf-8"))
    build_player_diagnostics(con)
    con.execute("""CREATE TABLE diagnostics.guest_coverage AS
      SELECT 'ledger_outside_analysis_window' AS metric,count(*)::BIGINT AS records,
        coalesce(sum(economic_cost_cents*0.01),0)::DECIMAL(24,2) AS amount_usd
      FROM staging.loyalty_events l CROSS JOIN staging.analysis_window w
      WHERE l.gaming_date NOT BETWEEN w.start_date AND w.end_date
      UNION ALL SELECT 'visits_outside_first_gaming_date_window',count(*)::BIGINT,
        coalesce(sum(coin_in_usd),0)::DECIMAL(24,2)
      FROM staging.visit_facts v CROSS JOIN staging.analysis_window w
      WHERE v.first_gaming_date NOT BETWEEN w.start_date AND w.end_date
      UNION ALL SELECT 'carded_pos_without_visit',count(*)::BIGINT,
        coalesce(sum(cash_receipt_cents*0.01),0)::DECIMAL(24,2)
      FROM raw.fnb_transactions p CROSS JOIN staging.analysis_window w WHERE p.player_id IS NOT NULL
        AND p.observed_visit_id IS NULL AND staging.gaming_date(p.event_at_utc) BETWEEN w.start_date AND w.end_date
      UNION ALL SELECT 'redemptions_without_pos',count(*)::BIGINT,
        coalesce(sum(economic_cost_cents*0.01),0)::DECIMAL(24,2)
      FROM raw.loyalty_ledger WHERE event_type='redeem' AND redeemed_pos_id IS NULL""")


def validate_guests(con):
    checks = [check for contract in CONTRACTS for check in validate_contract(con, contract)]

    def check(name, query):
        checks.append(check_query(con, name, query))

    check("guests.source_gaming_dates", """SELECT count(*) FROM raw.sessions
        WHERE gaming_date IS DISTINCT FROM staging.gaming_date(start_utc)""")
    check("guests.enrollment", """SELECT count(*) FROM staging.player_day d
        JOIN staging.player_identity i USING(player_id) WHERE d.gaming_date<i.enrolled_gaming_date""")
    check("guests.individual_points_balance", """WITH instants AS (
        SELECT player_id,event_at_utc,sum(points_delta) AS change FROM staging.loyalty_events l
        CROSS JOIN staging.analysis_window w WHERE l.gaming_date>=date_trunc('year',w.start_date)::DATE
          AND l.gaming_date<=w.end_date GROUP BY player_id,event_at_utc
        ), balances AS (SELECT sum(change) OVER(PARTITION BY player_id ORDER BY event_at_utc
          ROWS UNBOUNDED PRECEDING) AS balance FROM instants)
        SELECT count(*) FROM balances WHERE balance<0""")
    check("mart_player_month.source_coverage", """SELECT abs(
        (SELECT count(*) FROM marts.mart_player_month)-
        (SELECT count(*) FROM raw.player_period p CROSS JOIN staging.analysis_window w
          WHERE cast(p.period_month||'-01' AS DATE) BETWEEN w.start_date AND w.end_date))""")
    metrics = ("tracked_coin_in_usd", "tracked_payout_usd", "linked_pos_cash_usd", "linked_pos_cogs_usd",
               "comp_cost_usd", "comp_face_value_usd", "points_earned", "points_redeemed", "comps_redeemed")
    mismatches = " OR ".join(f"m.{name} IS DISTINCT FROM coalesce(f.{name},0)" for name in metrics)
    check("mart_player_month.independent_fact_reconciliation", f"""SELECT count(*) FROM marts.mart_player_month m
        FULL JOIN staging.player_fact_month f USING(player_id,month_start)
        WHERE m.player_id IS NULL OR {mismatches}
        OR abs(m.theo_usd-coalesce(f.tracked_theo_usd,0))>0.00005001""")
    check("mart_player_month.session_counts", """WITH s AS (
        SELECT player_id,date_trunc('month',gaming_date)::DATE AS month_start,
          count(DISTINCT logical_session_id) AS n,
          sum(date_diff('microsecond',start_utc,end_utc))/3600000000.0 AS hours
        FROM raw.sessions GROUP BY player_id,month_start)
        SELECT count(*) FROM marts.mart_player_month p LEFT JOIN s USING(player_id,month_start)
        WHERE p.sessions<>coalesce(s.n,0) OR abs(p.carded_play_hours-coalesce(s.hours,0))>greatest(1,p.sessions)*0.000001""")
    check("mart_player_month.accounting", """SELECT count(*) FROM marts.mart_player_month WHERE
        tracked_net_usd<>tracked_payout_usd-tracked_coin_in_usd OR actual_tracked_loss_usd<>-tracked_net_usd
        OR tracked_contribution_usd<>actual_tracked_loss_usd+linked_pos_cash_usd-linked_pos_cogs_usd
        OR abs(luck_residual_usd-(tracked_net_usd+theo_usd))>0.00000001
        OR winner_flag IS DISTINCT FROM (tracked_net_usd>0) OR observed_visits<incomplete_visits
        OR observed_visits<0 OR incomplete_visits<0 OR sessions<0 OR carded_play_hours<0
        OR above_expected_loss_flag IS NOT NULL""")
    check("mart_visits_month.raw_coverage", """SELECT abs(
        (SELECT coalesce(sum(observed_visits),0) FROM marts.mart_visits_month)-
        (SELECT count(*) FROM raw.trips t CROSS JOIN staging.analysis_window w
          WHERE staging.gaming_date(t.first_observed_at_utc) BETWEEN w.start_date AND w.end_date))""")
    check("mart_visits_month.accounting", """SELECT count(*) FROM marts.mart_visits_month WHERE
        observed_visits<>complete_visits+incomplete_visits OR winning_visits>complete_gaming_visits
        OR complete_gaming_visits>visits_with_gaming OR visits_with_gaming>observed_visits
        OR unique_players>observed_visits
        OR visit_assigned_player_net_usd<>visit_assigned_payout_usd-visit_assigned_coin_in_usd
        OR winner_share_complete_visits IS DISTINCT FROM winning_visits::DOUBLE/nullif(complete_gaming_visits,0)
        OR coin_in_per_visit IS DISTINCT FROM visit_assigned_coin_in_usd::DOUBLE/observed_visits""")
    check("mart_visits_month.independent_play_totals", """WITH s AS (
        SELECT coalesce(sum(s.coin_in_cents*0.01),0) AS coin,coalesce(sum(s.payout_cents*0.01),0) AS payout
        FROM raw.sessions s JOIN raw.trips t USING(observed_visit_id) CROSS JOIN staging.analysis_window w
        WHERE staging.gaming_date(t.first_observed_at_utc) BETWEEN w.start_date AND w.end_date)
        SELECT count(*) FROM s WHERE s.coin IS DISTINCT FROM
          (SELECT coalesce(sum(visit_assigned_coin_in_usd),0) FROM marts.mart_visits_month)
        OR s.payout IS DISTINCT FROM (SELECT coalesce(sum(visit_assigned_payout_usd),0) FROM marts.mart_visits_month)""")
    check("mart_visits_month.independent_pos_totals", """SELECT count(*) FROM (
        SELECT coalesce(sum(p.cash_receipt_cents*0.01),0) AS cash FROM raw.fnb_transactions p
        JOIN raw.trips t USING(observed_visit_id) CROSS JOIN staging.analysis_window w
        WHERE staging.gaming_date(t.first_observed_at_utc) BETWEEN w.start_date AND w.end_date)
        WHERE cash IS DISTINCT FROM (SELECT coalesce(sum(visit_assigned_pos_cash_usd),0) FROM marts.mart_visits_month)""")
    check("mart_comps_daily.calendar_coverage", """SELECT abs(
        (SELECT count(*) FROM marts.mart_comps_daily)-
        (SELECT date_diff('day',start_date,end_date)+1 FROM staging.analysis_window))""")
    check("mart_comps_daily.carded_meter_reconciliation", """WITH meters AS (
        SELECT gaming_date,sum(carded_coin_in_cents*0.01) AS coin,sum(carded_payout_cents*0.01) AS payout
        FROM raw.machine_day GROUP BY gaming_date)
        SELECT count(*) FROM marts.mart_comps_daily c LEFT JOIN meters d USING(gaming_date)
        WHERE c.tracked_coin_in_usd IS DISTINCT FROM coalesce(d.coin,0)
          OR c.tracked_payout_usd IS DISTINCT FROM coalesce(d.payout,0)""")
    check("mart_comps_daily.floor_comp_reconciliation", """SELECT count(*) FROM marts.mart_comps_daily c
        LEFT JOIN marts.mart_floor_daily f USING(gaming_date)
        WHERE c.comp_cost_usd IS DISTINCT FROM f.comp_cost_usd""")
    for contract in (COMPS_DAILY, COMPS_TIER):
        name = contract.name
        check(name + ".accounting", f"""SELECT count(*) FROM marts.{name} WHERE
            actual_tracked_loss_usd<>tracked_coin_in_usd-tracked_payout_usd
            OR total_tracked_spend_usd<>actual_tracked_loss_usd+linked_pos_cash_usd
            OR tracked_contribution_usd<>total_tracked_spend_usd-linked_pos_cogs_usd
            OR points_balance_change<>points_earned-points_redeemed
            OR points_balance_end<>points_balance_start+points_balance_change
            OR points_earned<0 OR points_redeemed<0 OR points_balance_start<0 OR points_balance_end<0
            OR policy_change_candidate IS NOT NULL""")
        check(name + ".denominators", f"""SELECT count(*) FROM marts.{name} WHERE
            comp_cost_per_actual_loss IS DISTINCT FROM CASE WHEN actual_tracked_loss_usd>0 THEN comp_cost_usd::DOUBLE/actual_tracked_loss_usd END
            OR comp_cost_per_total_spend IS DISTINCT FROM CASE WHEN total_tracked_spend_usd>0 THEN comp_cost_usd::DOUBLE/total_tracked_spend_usd END
            OR comp_cost_per_coin_in IS DISTINCT FROM comp_cost_usd::DOUBLE/nullif(tracked_coin_in_usd,0)
            OR theo_per_comp_cost IS DISTINCT FROM tracked_theo_usd::DOUBLE/nullif(comp_cost_usd,0)
            OR actual_loss_ratio_status<>CASE WHEN actual_tracked_loss_usd>0 THEN 'positive_denominator' WHEN actual_tracked_loss_usd=0 THEN 'zero_denominator' ELSE 'negative_denominator' END
            OR total_spend_ratio_status<>CASE WHEN total_tracked_spend_usd>0 THEN 'positive_denominator' WHEN total_tracked_spend_usd=0 THEN 'zero_denominator' ELSE 'negative_denominator' END""")
    check("mart_comps_daily.balance_rollforward", """SELECT count(*) FROM (
        SELECT points_balance_start,lag(points_balance_end) OVER(ORDER BY gaming_date) AS previous_end
        FROM marts.mart_comps_daily) WHERE previous_end IS NOT NULL AND points_balance_start<>previous_end""")
    check("guests.points_snapshot_reconciliation", """SELECT count(*) FROM staging.analysis_window w WHERE
        (SELECT points_balance_start FROM marts.mart_comps_daily ORDER BY gaming_date LIMIT 1)
        IS DISTINCT FROM (SELECT coalesce(sum(points_delta),0) FROM staging.loyalty_events l
          WHERE l.gaming_date>=date_trunc('year',w.start_date)::DATE AND l.gaming_date<w.start_date)
        OR (SELECT points_balance_end FROM marts.mart_comps_daily ORDER BY gaming_date DESC LIMIT 1)
        IS DISTINCT FROM (SELECT coalesce(sum(points_delta),0) FROM staging.loyalty_events l
          WHERE l.gaming_date>=date_trunc('year',w.start_date)::DATE AND l.gaming_date<=w.end_date)""")
    check("mart_comps_tier_month.balance_rollforward", """SELECT count(*) FROM (
        SELECT points_balance_start,lag(points_balance_end) OVER(PARTITION BY opening_tier ORDER BY month_start) AS previous_end
        FROM marts.mart_comps_tier_month) WHERE previous_end IS NOT NULL AND points_balance_start<>previous_end""")
    check("mart_comps_tier_month.cohort_coverage", """SELECT abs(
        (SELECT count(*) FROM marts.mart_comps_tier_month)-
        (SELECT count(DISTINCT opening_tier) FROM staging.player_identity)*
        (SELECT count(DISTINCT date_trunc('month',gaming_date)) FROM marts.mart_comps_daily))""")
    additive = ECONOMIC_MONEY + ("points_earned", "points_redeemed", "points_balance_change")
    daily_sums = ", ".join(f"sum({metric}) AS {metric}" for metric in additive)
    delta = " OR ".join(f"d.{metric} IS DISTINCT FROM t.{metric}" for metric in additive)
    check("guests.daily_tier_month_reconciliation", f"""WITH d AS (
        SELECT month_start,{daily_sums},arg_min(points_balance_start,gaming_date) AS balance_start,
          arg_max(points_balance_end,gaming_date) AS balance_end FROM marts.mart_comps_daily GROUP BY month_start
        ), t AS (SELECT month_start,{daily_sums},sum(points_balance_start) AS balance_start,
          sum(points_balance_end) AS balance_end FROM marts.mart_comps_tier_month GROUP BY month_start)
        SELECT count(*) FROM d FULL JOIN t USING(month_start) WHERE d.month_start IS NULL OR t.month_start IS NULL
          OR {delta} OR d.balance_start<>t.balance_start OR d.balance_end<>t.balance_end""")
    check("guests.theo_rounding_reconciliation", """WITH d AS (
        SELECT month_start,sum(tracked_theo_usd) AS theo,count(*) AS n FROM marts.mart_comps_daily GROUP BY month_start
        ), t AS (SELECT month_start,sum(tracked_theo_usd) AS theo,count(*) AS n
          FROM marts.mart_comps_tier_month GROUP BY month_start)
        SELECT count(*) FROM d JOIN t USING(month_start) WHERE abs(d.theo-t.theo)>(d.n+t.n)*0.00000001""")
    check("mart_comps_tier_month.player_month_reconciliation", """WITH p AS (
        SELECT opening_tier,month_start,sum(tracked_coin_in_usd) AS coin,sum(comp_cost_usd) AS cost,
          sum(points_earned) AS earned,sum(points_redeemed) AS redeemed
        FROM marts.mart_player_month GROUP BY opening_tier,month_start)
        SELECT count(*) FROM marts.mart_comps_tier_month c LEFT JOIN p USING(opening_tier,month_start)
        WHERE c.tracked_coin_in_usd IS DISTINCT FROM coalesce(p.coin,0)
          OR c.comp_cost_usd IS DISTINCT FROM coalesce(p.cost,0)
          OR c.points_earned IS DISTINCT FROM coalesce(p.earned,0)
          OR c.points_redeemed IS DISTINCT FROM coalesce(p.redeemed,0)
          OR c.active_players>c.cohort_players""")
    return checks
