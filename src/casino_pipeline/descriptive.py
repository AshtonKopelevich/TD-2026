"""Stage-three contracts, builders, and reconciliation for descriptive marts."""

from dataclasses import dataclass
from pathlib import Path

from .database import quote_identifier
from .machine_daily import SCHEMA as DAILY_SCHEMA, MONEY, THEO


@dataclass(frozen=True)
class MartContract:
    name: str
    key: tuple[str, ...]
    columns: dict[str, str]
    nullable: frozenset[str] = frozenset()


MACHINE_SUMS = tuple(name for name, dtype in DAILY_SCHEMA.items()
                     if dtype in (MONEY, THEO) or name in (
                         "scheduled_seconds", "available_seconds", "occupied_seconds", "paid_spins", "carded_spins"))
RATIOS = tuple("availability_ratio occupancy_ratio observed_hold expected_hold carded_coin_in_share coin_in_per_available_hour theo_per_available_hour expected_contribution_per_available_hour".split())
STATS = tuple("luck_z_score luck_p_value luck_q_value bootstrap_hold_gap_low bootstrap_hold_gap_high".split())
MONTH = MartContract("mart_machine_month", ("machine_id", "month_start"), {
    "machine_id": "VARCHAR", "month_start": "DATE", "period_start": "DATE", "period_end": "DATE",
    "active_days": "BIGINT", "manufacturer": "VARCHAR", "lease_class": "VARCHAR",
    **{name: DAILY_SCHEMA[name] for name in MACHINE_SUMS},
    **dict.fromkeys(RATIOS, "DOUBLE"), "location_count": "BIGINT", "config_count": "BIGINT",
    "outcome_variance_usd2": "DOUBLE", **dict.fromkeys(STATS, "DOUBLE"), "statistical_status": "VARCHAR",
}, frozenset(RATIOS + STATS))
FLOOR = MartContract("mart_floor_daily", ("gaming_date",), {
    "gaming_date": "DATE", "month_start": "DATE", "weekday_index": "BIGINT", "is_weekend": "BOOLEAN",
    "federal_holiday": "VARCHAR", "events_active": "VARCHAR", "active_machines": "BIGINT",
    **dict.fromkeys("scheduled_machine_hours available_machine_hours occupied_machine_hours".split(), "DOUBLE"),
    **dict.fromkeys("coin_in_usd payout_usd house_win_usd carded_coin_in_usd pos_cash_usd pos_cogs_usd comp_cost_usd machine_cost_usd tech_labor_cost_usd actual_floor_contribution_usd".split(), MONEY),
    "theo_usd": THEO, "carded_coin_in_share": "DOUBLE", "coin_in_per_active_machine_day": "DOUBLE",
    "weather_temperature_max_c": "DOUBLE", "weather_precipitation_mm": "DOUBLE",
    "weather_precipitation_trace": "BOOLEAN", "weather_status": "VARCHAR",
}, frozenset("federal_holiday events_active carded_coin_in_share coin_in_per_active_machine_day weather_temperature_max_c weather_precipitation_mm weather_precipitation_trace".split()))
ZONE = MartContract("mart_zone_daily", ("zone_id", "gaming_date"), {
    "zone_id": "VARCHAR", "zone_name": "VARCHAR", "gaming_date": "DATE", "month_start": "DATE",
    **dict.fromkeys("active_machines scheduled_seconds available_seconds occupied_seconds".split(), "BIGINT"),
    "coin_in_usd": MONEY, "house_win_usd": MONEY, "theo_usd": THEO,
    "coin_in_per_available_hour": "DOUBLE", "theo_per_available_hour": "DOUBLE",
    **dict.fromkeys("entries_observed counter_observed_seconds counter_expected_seconds counter_missing_seconds sensor_count".split(), "BIGINT"),
    "counter_coverage_ratio": "DOUBLE", "traffic_status": "VARCHAR", "counter_schedule_basis": "VARCHAR",
}, frozenset("coin_in_per_available_hour theo_per_available_hour entries_observed counter_coverage_ratio".split()))
BENCHMARK = MartContract("mart_benchmark_month", ("month_start",), {
    "month_start": "DATE", "index_base_month": "DATE", "property_observed_days": "BIGINT", "property_period_complete": "BOOLEAN",
    "property_coin_in_usd": MONEY, "property_house_win_usd": MONEY, "property_active_machine_days": "BIGINT",
    "property_coin_in_per_machine_day": "DOUBLE", "missouri_coin_in_usd": MONEY, "missouri_house_win_usd": MONEY,
    "las_vegas_visitor_volume": "BIGINT",
    **dict.fromkeys("property_coin_in_index missouri_coin_in_index las_vegas_visitors_index".split(), "DOUBLE"),
    "missouri_status": "VARCHAR", "visitation_status": "VARCHAR", "missouri_source_url": "VARCHAR",
    "visitation_source_url": "VARCHAR", "source_revision": "VARCHAR", "as_of_limitation": "VARCHAR",
    "missouri_retrieved_date": "DATE",
}, frozenset("property_coin_in_per_machine_day missouri_coin_in_usd missouri_house_win_usd las_vegas_visitor_volume property_coin_in_index missouri_coin_in_index las_vegas_visitors_index missouri_source_url visitation_source_url source_revision as_of_limitation missouri_retrieved_date".split()))
CONTRACTS = (MONTH, FLOOR, ZONE, BENCHMARK)


def check_query(con, name, sql):
    failures = con.execute(sql).fetchone()[0]
    return {"check": name, "passed": failures == 0, "detail": {"violations": failures}}


def validate_inputs(con):
    """Reject ambiguous context joins and invalid observed traffic before aggregation."""
    checks = []
    for table, keys in (("weather_daily", "station_id, source_date"),
                        ("benchmark_state_monthly", "month"), ("city_visitation_monthly", "month")):
        nulls = " OR ".join(f"{key.strip()} IS NULL" for key in keys.split(","))
        checks.append(check_query(con, f"{table}.context_key", f"""SELECT
            (SELECT count(*) FROM raw.{table} WHERE {nulls}) +
            (SELECT count(*) FROM (SELECT {keys} FROM raw.{table} GROUP BY ALL HAVING count(*) > 1))"""))
    checks.append(check_query(con, "context.calendar_complete", """SELECT abs(
        (SELECT count(*) FROM raw.calendar_day c, staging.analysis_window w
         WHERE c.gaming_date BETWEEN w.start_date AND w.end_date) -
        (SELECT date_diff('day',start_date,end_date)+1 FROM staging.analysis_window))"""))
    checks.append(check_query(con, "traffic.stable_sensor_zone", """SELECT count(*) FROM (
        SELECT sensor_id FROM raw.zone_traffic_hourly GROUP BY sensor_id
        HAVING count(DISTINCT zone_id) <> 1 OR count(zone_id) <> count(*))"""))
    checks.append(check_query(con, "traffic.valid_observations", """SELECT count(*) FROM raw.zone_traffic_hourly
        WHERE hour_start_utc IS NULL OR date_trunc('hour',hour_start_utc) <> hour_start_utc
          OR coverage_minutes IS NULL OR coverage_minutes NOT BETWEEN 0 AND 60
          OR counter_status IS NULL OR counter_status NOT IN ('ok','partial','offline')
          OR (counter_status='offline' AND (coverage_minutes<>0 OR entries_count IS NOT NULL))
          OR (counter_status='ok' AND coverage_minutes<>60)
          OR (counter_status='partial' AND coverage_minutes NOT BETWEEN 1 AND 59)
          OR (coverage_minutes>0 AND (entries_count IS NULL OR entries_count<0))"""))
    checks.append(check_query(con, "context.valid_month_keys", """SELECT count(*) FROM (
        SELECT month FROM raw.benchmark_state_monthly UNION ALL SELECT month FROM raw.city_visitation_monthly
        ) WHERE NOT regexp_full_match(month,'[0-9]{4}-[0-9]{2}')
          OR try_cast(month || '-01' AS DATE) IS NULL"""))
    return checks


def build_descriptive(con):
    root = Path(__file__).resolve().parents[2] / "sql"
    con.execute((root / "staging" / "context.sql").read_text(encoding="utf-8"))
    for contract in CONTRACTS:
        con.execute((root / "marts" / (contract.name.removeprefix("mart_") + ".sql")).read_text(encoding="utf-8"))


def validate_contract(con, contract):
    table = f"marts.{contract.name}"
    observed = {r[0]: r[1] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    checks = [{"check": f"{contract.name}.schema", "passed": observed == contract.columns,
               "detail": {"expected": contract.columns, "actual": observed}}]
    columns = ", ".join(quote_identifier(key) for key in contract.key)
    checks.append(check_query(con, f"{contract.name}.key", f"SELECT count(*) FROM (SELECT {columns} FROM {table} GROUP BY ALL HAVING count(*)>1)"))
    nulls = " OR ".join(f'{quote_identifier(name)} IS NULL' for name in contract.columns if name not in contract.nullable)
    checks.append(check_query(con, f"{contract.name}.required_values", f"SELECT count(*) FROM {table} WHERE {nulls}"))
    return checks


def finalize_contract(con, contract):
    table = f"marts.{contract.name}"
    for name in contract.columns:
        if name not in contract.nullable:
            con.execute(f"ALTER TABLE {table} ALTER COLUMN {quote_identifier(name)} SET NOT NULL")
    key = ", ".join(quote_identifier(name) for name in contract.key)
    has_key = con.execute("""SELECT count(*) FROM duckdb_constraints()
        WHERE schema_name='marts' AND table_name=? AND constraint_type='PRIMARY KEY'""", [contract.name]).fetchone()[0]
    if not has_key:
        con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({key})")
    return {"name": table, "rows": con.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            "key": list(contract.key), "columns": [
                {"name": name, "type": dtype, "nullable": name in contract.nullable}
                for name, dtype in contract.columns.items()]}


def validate_descriptive(con):
    checks = [check for contract in CONTRACTS for check in validate_contract(con, contract)]

    def check(name, query):
        checks.append(check_query(con, name, query))

    sums = ", ".join(f"sum({name}) AS {name}" for name in MACHINE_SUMS)
    mismatches = " OR ".join(f"m.{name} IS DISTINCT FROM d.{name}" for name in MACHINE_SUMS)
    check("mart_machine_month.daily_reconciliation", f"""WITH d AS (
        SELECT machine_id,month_start,{sums},count(*) AS active_days,
          min(gaming_date) AS period_start,max(gaming_date) AS period_end,
          count(DISTINCT location_id) AS location_count,count(DISTINCT config_id) AS config_count
        FROM marts.mart_machine_daily GROUP BY machine_id,month_start)
        SELECT count(*) FROM marts.mart_machine_month m FULL JOIN d USING(machine_id,month_start)
        WHERE m.machine_id IS NULL OR d.machine_id IS NULL OR {mismatches}
          OR m.active_days<>d.active_days OR m.period_start<>d.period_start OR m.period_end<>d.period_end
          OR m.location_count<>d.location_count OR m.config_count<>d.config_count""")
    for contract in (MONTH,):
        conditions = [f"{name} IS NOT NULL" for name in STATS]
        check(f"{contract.name}.statistics_initialized_deferred", f"SELECT count(*) FROM marts.{contract.name} WHERE " +
              " OR ".join(conditions + ["statistical_status<>'not_implemented'"]))
    formulas = {"availability_ratio": "available_seconds::DOUBLE/nullif(scheduled_seconds,0)",
                "occupancy_ratio": "occupied_seconds::DOUBLE/nullif(available_seconds,0)",
                "observed_hold": "house_win_usd::DOUBLE/nullif(coin_in_usd,0)",
                "expected_hold": "theo_usd::DOUBLE/nullif(coin_in_usd,0)",
                "carded_coin_in_share": "carded_coin_in_usd::DOUBLE/nullif(coin_in_usd,0)",
                **{name: numerator + "::DOUBLE/nullif(available_seconds/3600.0,0)" for name, numerator in (
                    ("coin_in_per_available_hour", "coin_in_usd"), ("theo_per_available_hour", "theo_usd"),
                    ("expected_contribution_per_available_hour", "expected_contribution_usd"))}}
    check("mart_machine_month.ratios_of_sums", "SELECT count(*) FROM marts.mart_machine_month WHERE " +
          " OR ".join(f"{name} IS DISTINCT FROM ({formula})" for name, formula in formulas.items()))
    check("mart_floor_daily.calendar_coverage", """SELECT abs(
        (SELECT count(*) FROM marts.mart_floor_daily) -
        (SELECT date_diff('day',start_date,end_date)+1 FROM staging.analysis_window))""")
    check("mart_floor_daily.source_accounting", """SELECT count(*) FROM marts.mart_floor_daily f
        LEFT JOIN raw.property_day p USING(gaming_date) WHERE p.gaming_date IS NULL
        OR f.active_machines IS DISTINCT FROM p.active_machines
        OR f.coin_in_usd IS DISTINCT FROM p.coin_in_usd OR f.payout_usd IS DISTINCT FROM p.payout_usd
        OR f.house_win_usd IS DISTINCT FROM p.house_win_usd
        OR p.theo_usd IS NULL OR abs(f.theo_usd-p.theo_usd)>0.00005002
        OR p.machine_supplied_costs_usd IS NULL OR f.machine_cost_usd<>p.machine_supplied_costs_usd
        OR p.available_machine_hours IS NULL OR abs(f.available_machine_hours-p.available_machine_hours)>greatest(1,f.active_machines)*0.000001
        OR p.occupied_machine_hours IS NULL OR abs(f.occupied_machine_hours-p.occupied_machine_hours)>greatest(1,f.active_machines)*0.000001
        OR p.contribution_after_supplied_costs_usd IS NULL
        OR f.actual_floor_contribution_usd<>p.contribution_after_supplied_costs_usd
        OR f.actual_floor_contribution_usd<>f.house_win_usd+f.pos_cash_usd-f.pos_cogs_usd-f.machine_cost_usd-f.tech_labor_cost_usd""")
    check("mart_floor_daily.ratio_definitions", """SELECT count(*) FROM marts.mart_floor_daily WHERE
        carded_coin_in_share IS DISTINCT FROM carded_coin_in_usd::DOUBLE/nullif(coin_in_usd,0)
        OR coin_in_per_active_machine_day IS DISTINCT FROM coin_in_usd::DOUBLE/nullif(active_machines,0)""")
    check("mart_zone_daily.zone_date_coverage", """SELECT abs(
        (SELECT count(*) FROM marts.mart_zone_daily) -
        (SELECT count(DISTINCT zone_id) FROM raw.floor_locations WHERE node_type='slot') *
        (SELECT count(*) FROM marts.mart_floor_daily))""")
    check("mart_zone_daily.floor_reconciliation", """WITH z AS (
        SELECT gaming_date,sum(active_machines) AS active_machines,sum(coin_in_usd) AS coin,
          sum(house_win_usd) AS win,sum(theo_usd) AS theo,sum(available_seconds)/3600.0 AS hours
        FROM marts.mart_zone_daily GROUP BY gaming_date)
        SELECT count(*) FROM z FULL JOIN marts.mart_floor_daily f USING(gaming_date)
        WHERE z.gaming_date IS NULL OR f.gaming_date IS NULL OR z.active_machines<>f.active_machines
          OR z.coin<>f.coin_in_usd OR z.win<>f.house_win_usd OR z.theo<>f.theo_usd
          OR abs(z.hours-f.available_machine_hours)>0.0000001""")
    check("mart_zone_daily.traffic_coverage", """SELECT count(*) FROM marts.mart_zone_daily WHERE
        counter_observed_seconds NOT BETWEEN 0 AND counter_expected_seconds
        OR counter_missing_seconds NOT BETWEEN 0 AND counter_expected_seconds-counter_observed_seconds
        OR counter_coverage_ratio IS DISTINCT FROM counter_observed_seconds::DOUBLE/nullif(counter_expected_seconds,0)
        OR (counter_observed_seconds=0 AND entries_observed IS NOT NULL)
        OR (counter_observed_seconds>0 AND entries_observed IS NULL)""")
    check("mart_zone_daily.traffic_reconciliation", """SELECT count(*) FROM marts.mart_zone_daily z
        LEFT JOIN staging.traffic_daily t USING(zone_id,gaming_date)
        WHERE z.entries_observed IS DISTINCT FROM t.entries_observed
        OR z.counter_observed_seconds<>coalesce(t.observed_seconds,0)""")
    check("mart_zone_daily.ratio_definitions", """SELECT count(*) FROM marts.mart_zone_daily WHERE
        coin_in_per_available_hour IS DISTINCT FROM coin_in_usd::DOUBLE/nullif(available_seconds/3600.0,0)
        OR theo_per_available_hour IS DISTINCT FROM theo_usd::DOUBLE/nullif(available_seconds/3600.0,0)""")
    check("mart_benchmark_month.floor_reconciliation", """WITH f AS (
        SELECT month_start,sum(coin_in_usd) AS coin,sum(house_win_usd) AS win,
          sum(active_machines) AS machines,count(*) AS days FROM marts.mart_floor_daily GROUP BY month_start)
        SELECT count(*) FROM f FULL JOIN marts.mart_benchmark_month b USING(month_start)
        WHERE f.month_start IS NULL OR b.month_start IS NULL OR f.coin<>b.property_coin_in_usd
          OR f.win<>b.property_house_win_usd OR f.machines<>b.property_active_machine_days
          OR f.days<>b.property_observed_days""")
    check("mart_benchmark_month.external_reconciliation", """SELECT count(*) FROM marts.mart_benchmark_month b
        LEFT JOIN raw.benchmark_state_monthly m ON m.month=strftime(b.month_start,'%Y-%m')
        LEFT JOIN raw.city_visitation_monthly v ON v.month=strftime(b.month_start,'%Y-%m')
        WHERE b.missouri_coin_in_usd IS DISTINCT FROM m.handle_usd
          OR b.missouri_house_win_usd IS DISTINCT FROM m.agr_usd
          OR b.las_vegas_visitor_volume IS DISTINCT FROM v.visitor_volume""")
    check("mart_benchmark_month.january_indices", """SELECT count(*) FROM marts.mart_benchmark_month
        WHERE (month(month_start)=1 AND property_period_complete AND property_coin_in_usd>0
               AND property_coin_in_index IS DISTINCT FROM 100.0)
          OR (NOT property_period_complete AND property_coin_in_index IS NOT NULL)
          OR (month(month_start)=1 AND missouri_coin_in_usd>0 AND missouri_coin_in_index IS DISTINCT FROM 100.0)
          OR (month(month_start)=1 AND las_vegas_visitor_volume>0 AND las_vegas_visitors_index IS DISTINCT FROM 100.0)""")
    return checks
