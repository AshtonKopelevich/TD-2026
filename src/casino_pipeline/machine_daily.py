"""Build and validate the first materialized mart."""

from pathlib import Path

from .constants import ANALYSIS_START, ANALYSIS_END

MONEY = "DECIMAL(24,2)"
THEO = "DECIMAL(28,8)"
SCHEMA = {
    **dict.fromkeys("machine_id location_id zone_id bank_id config_id zone_name manufacturer theme lease_class meter_status volatility_class".split(), "VARCHAR"),
    **dict.fromkeys("gaming_date month_start".split(), "DATE"), "active": "BOOLEAN",
    **dict.fromkeys("scheduled_seconds available_seconds occupied_seconds paid_spins carded_spins calendar_day_seconds faults_opened".split(), "BIGINT"),
    **dict.fromkeys("coin_in_usd payout_usd house_win_usd carded_coin_in_usd carded_payout_usd lease_cost_usd service_cost_usd power_cost_usd repair_cost_usd machine_cost_usd actual_contribution_usd".split(), MONEY),
    **dict.fromkeys("theo_usd carded_theo_usd luck_residual_usd expected_contribution_usd".split(), THEO),
    **dict.fromkeys("x_m y_m configured_rtp payout_multiplier_variance sum_bet_squared_cents2 outcome_variance_usd2 availability_ratio occupancy_ratio observed_hold expected_hold carded_coin_in_share coin_in_per_available_hour theo_per_available_hour expected_contribution_per_available_hour".split(), "DOUBLE"),
}
NULLABLE = set("x_m y_m availability_ratio occupancy_ratio observed_hold expected_hold carded_coin_in_share coin_in_per_available_hour theo_per_available_hour expected_contribution_per_available_hour".split())


def build_machine_daily(con):
    con.execute("CREATE TABLE staging.analysis_window AS SELECT ?::DATE AS start_date, ?::DATE AS end_date",
                [ANALYSIS_START, ANALYSIS_END])
    sql = Path(__file__).resolve().parents[2] / "sql" / "marts" / "machine_daily.sql"
    con.execute(sql.read_text(encoding="utf-8"))


def validate_machine_daily(con):
    checks = []

    def check(name, failures):
        checks.append({"check": f"mart_machine_daily.{name}", "passed": failures == 0,
                       "detail": {"violations": failures}})

    def scalar(sql):
        return con.execute(sql).fetchone()[0]

    expected = scalar("""SELECT count(*) FROM raw.machine_day d, staging.analysis_window w
                         WHERE d.active AND d.gaming_date BETWEEN w.start_date AND w.end_date""")
    actual = scalar("SELECT count(*) FROM marts.mart_machine_daily")
    check("active_row_coverage", abs(expected - actual))
    check("nonempty", int(actual == 0))
    observed = {r[0]: r[1] for r in con.execute("DESCRIBE marts.mart_machine_daily").fetchall()}
    check("schema", int(observed != SCHEMA))
    required = [f'"{name}" IS NULL' for name in SCHEMA if name not in NULLABLE]
    check("required_values", scalar("SELECT count(*) FROM marts.mart_machine_daily WHERE " + " OR ".join(required)))
    check("key", scalar("""SELECT count(*) FROM (SELECT machine_id, gaming_date FROM marts.mart_machine_daily
                          GROUP BY ALL HAVING count(*) > 1)"""))
    check("duration_bounds", scalar("""SELECT count(*) FROM marts.mart_machine_daily WHERE NOT
         (0 <= occupied_seconds AND occupied_seconds <= available_seconds
          AND available_seconds <= scheduled_seconds AND scheduled_seconds <= calendar_day_seconds)"""))
    check("meter_identities", scalar("""SELECT count(*) FROM marts.mart_machine_daily WHERE
          house_win_usd <> coin_in_usd - payout_usd OR paid_spins < 0 OR carded_spins < 0
          OR carded_spins > paid_spins OR coin_in_usd < 0 OR carded_coin_in_usd < 0
          OR carded_coin_in_usd > coin_in_usd OR carded_payout_usd > payout_usd
          OR carded_theo_usd > theo_usd OR payout_usd < 0 OR carded_payout_usd < 0
          OR outcome_variance_usd2 < 0 OR NOT isfinite(outcome_variance_usd2)"""))
    check("active_slot", scalar("""SELECT count(*) FROM marts.mart_machine_daily m
          LEFT JOIN raw.floor_locations l USING(location_id)
          WHERE NOT m.active OR nullif(trim(m.location_id), '') IS NULL OR l.node_type <> 'slot'
          OR m.zone_id IS DISTINCT FROM l.zone_id OR m.bank_id IS DISTINCT FROM l.bank_id"""))
    check("placement_intervals", scalar("""SELECT count(*) FROM (
        SELECT m.machine_id, m.gaming_date, count(p.placement_id) AS matches
        FROM marts.mart_machine_daily m JOIN raw.calendar_day c USING(gaming_date)
        LEFT JOIN raw.placements p ON p.machine_id = m.machine_id
          AND p.effective_from_utc < c.gaming_day_end_utc
          AND coalesce(p.effective_to_utc, TIMESTAMP '9999-12-31') > c.gaming_day_start_utc
        GROUP BY m.machine_id, m.gaming_date HAVING count(p.placement_id) <> 1
    )"""))
    check("placement_identity", scalar("""SELECT count(*) FROM marts.mart_machine_daily m
        JOIN raw.calendar_day c USING(gaming_date) JOIN raw.placements p ON p.machine_id=m.machine_id
         AND p.effective_from_utc < c.gaming_day_end_utc
         AND coalesce(p.effective_to_utc, TIMESTAMP '9999-12-31') > c.gaming_day_start_utc
        WHERE m.location_id IS DISTINCT FROM p.location_id OR m.config_id IS DISTINCT FROM p.config_id"""))
    check("scheduled_placement_overlap", scalar("""SELECT count(*) FROM marts.mart_machine_daily m
        JOIN raw.calendar_day c USING(gaming_date) JOIN raw.placements p ON p.machine_id=m.machine_id
         AND p.effective_from_utc < c.gaming_day_end_utc
         AND coalesce(p.effective_to_utc, TIMESTAMP '9999-12-31') > c.gaming_day_start_utc
        WHERE m.scheduled_seconds <> date_diff('second',
          greatest(p.effective_from_utc,c.gaming_day_start_utc),
          least(coalesce(p.effective_to_utc,c.gaming_day_end_utc),c.gaming_day_end_utc))"""))
    check("game_math_bounds", scalar("""SELECT count(*) FROM marts.mart_machine_daily WHERE
        configured_rtp NOT BETWEEN 0 AND 1 OR payout_multiplier_variance < 0
        OR sum_bet_squared_cents2 < 0 OR NOT isfinite(sum_bet_squared_cents2)"""))
    # Prepared views round theo to 4 decimal places and store hours as floating point.
    check("prepared_reconciliation", scalar("""SELECT count(*) FROM marts.mart_machine_daily m
        LEFT JOIN raw.prepared_daily_view p USING(machine_id, gaming_date)
        WHERE p.machine_id IS NULL OR NOT p.active
          OR m.location_id IS DISTINCT FROM p.location_id OR m.config_id IS DISTINCT FROM p.config_id
          OR m.coin_in_usd IS DISTINCT FROM p.coin_in_usd
          OR m.payout_usd IS DISTINCT FROM p.payout_usd
          OR m.house_win_usd IS DISTINCT FROM p.house_win_usd
          OR abs(m.theo_usd - p.theo_usd) > 0.00005001
          OR abs(m.available_seconds / 3600.0 - p.available_hours) > 0.000001
          OR abs(m.occupied_seconds / 3600.0 - p.occupied_hours) > 0.000001
          OR abs(m.actual_contribution_usd - p.contribution_after_supplied_costs_usd) > 0.005"""))
    check("accounting", scalar("""SELECT count(*) FROM marts.mart_machine_daily WHERE
          machine_cost_usd <> lease_cost_usd + service_cost_usd + power_cost_usd + repair_cost_usd
          OR actual_contribution_usd <> house_win_usd - machine_cost_usd
          OR abs(luck_residual_usd - (house_win_usd - theo_usd)) > 0.00000001
          OR abs(expected_contribution_usd - (theo_usd - machine_cost_usd)) > 0.00000001"""))
    check("ratio_definitions", scalar("""SELECT count(*) FROM marts.mart_machine_daily WHERE
          availability_ratio IS DISTINCT FROM available_seconds::DOUBLE / nullif(scheduled_seconds,0)
          OR occupancy_ratio IS DISTINCT FROM occupied_seconds::DOUBLE / nullif(available_seconds,0)
          OR observed_hold IS DISTINCT FROM house_win_usd::DOUBLE / nullif(coin_in_usd,0)
          OR theo_per_available_hour IS DISTINCT FROM theo_usd::DOUBLE / nullif(available_seconds / 3600.0,0)"""))
    return checks


def mart_inventory(con):
    return {"name": "marts.mart_machine_daily", "rows": con.execute(
        "SELECT count(*) FROM marts.mart_machine_daily").fetchone()[0],
        "key": ["machine_id", "gaming_date"], "columns": [
            {"name": name, "type": dtype, "nullable": name in NULLABLE}
            for name, dtype in SCHEMA.items()]}
