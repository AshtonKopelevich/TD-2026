"""Stage-five builders and contracts; estimates are retrospective gross losses."""

from pathlib import Path

from .. import constants as c
from ..descriptive import MartContract, check_query, validate_contract
from ..machine_daily import MONEY, THEO

TICKETS = MartContract("mart_tickets", ("operation_id",), {
    **dict.fromkeys("operation_id machine_id location_id event_type".split(), "VARCHAR"),
    "controllable_fault": "BOOLEAN", "gaming_date": "DATE",
    **dict.fromkeys("opened_at_utc recorded_at_utc work_started_at_utc available_at_utc".split(), "TIMESTAMP"),
    **dict.fromkeys("response_hours repair_hours total_outage_hours before_available_hours after_available_hours before_theo_per_hour after_theo_per_hour theo_rate_change".split(), "DOUBLE"),
    "direct_cost_usd": MONEY, "before_theo_usd": THEO, "after_theo_usd": THEO,
    "before_days": "BIGINT", "after_days": "BIGINT", "comparison_status": "VARCHAR",
    "truncated_window": "BOOLEAN", "context_changed": "BOOLEAN", "overlapping_faults": "BOOLEAN",
}, frozenset("location_id recorded_at_utc work_started_at_utc available_at_utc response_hours repair_hours total_outage_hours before_theo_per_hour after_theo_per_hour theo_rate_change".split()))
HOURLY = MartContract("mart_downtime_hourly", ("machine_id", "hour_start_utc"), {
    **dict.fromkeys("machine_id location_id zone_id bank_id config_id manufacturer utc_offset".split(), "VARCHAR"),
    "hour_start_utc": "TIMESTAMP", "gaming_date": "DATE", "local_hour": "BIGINT", "hour_band": "BIGINT",
    **dict.fromkeys("scheduled_seconds available_seconds occupied_seconds downtime_seconds fault_downtime_seconds planned_downtime_seconds other_downtime_seconds ticket_overlap_seconds unexplained_downtime_seconds neighbor_count reference_hours".split(), "BIGINT"),
    "coin_in_usd": MONEY, "payout_usd": MONEY, "theo_usd": THEO,
    **dict.fromkeys("neighbor_available_hours usual_rate_ratio usual_coin_in_rate_ratio available_tech_staff_hours".split(), "DOUBLE"),
    "estimated_lost_coin_in_usd": MONEY,
    **dict.fromkeys("estimated_lost_theo_usd lost_theo_low_usd lost_theo_high_usd".split(), THEO),
    "hidden_downtime_flag": "BOOLEAN", "hidden_downtime_status": "VARCHAR",
    "estimate_method": "VARCHAR", "estimate_status": "VARCHAR", "uncertainty_status": "VARCHAR",
    "outage_attribution_status": "VARCHAR",
}, frozenset("neighbor_available_hours usual_rate_ratio usual_coin_in_rate_ratio available_tech_staff_hours estimated_lost_coin_in_usd estimated_lost_theo_usd lost_theo_low_usd lost_theo_high_usd hidden_downtime_flag".split()))
CONTRACTS = (TICKETS, HOURLY)


def validate_inputs(con):
    queries = {
        "operations.timestamps": """SELECT count(*) FROM raw.operations WHERE opened_at_utc IS NULL
          OR (available_at_utc IS NOT NULL AND available_at_utc<opened_at_utc)
          OR (work_started_at_utc IS NOT NULL AND work_started_at_utc<opened_at_utc)
          OR (work_started_at_utc IS NOT NULL AND available_at_utc IS NOT NULL AND work_started_at_utc>available_at_utc)
          OR direct_cost_cents IS NULL OR direct_cost_cents<0 OR event_type IS NULL
          OR event_type NOT IN ('fault_repair','scheduled_maintenance','move','install','retire')""",
        "operations.machine_identity": """SELECT count(*) FROM raw.operations o LEFT JOIN raw.machines m USING(machine_id)
          WHERE m.machine_id IS NULL""",
        "machine_hour.bounds": """SELECT count(*) FROM raw.machine_hour WHERE NOT active OR active IS NULL
          OR available_seconds IS NULL OR occupied_seconds IS NULL OR available_seconds NOT BETWEEN 0 AND 3600
          OR occupied_seconds NOT BETWEEN 0 AND available_seconds OR coin_in_cents<0 OR payout_cents<0
          OR hour_start_utc IS NULL OR date_trunc('hour',hour_start_utc)<>hour_start_utc""",
        "shift_roster.intervals": """SELECT count(*) FROM raw.shift_roster
          WHERE start_utc IS NULL OR end_utc IS NULL OR end_utc<=start_utc OR role IS NULL""",
    }
    return [check_query(con, "downtime." + name, sql) for name, sql in queries.items()]


def build_downtime(con):
    if not (1 <= c.DOWNTIME_HOUR_BAND_HOURS <= 24 and 24 % c.DOWNTIME_HOUR_BAND_HOURS == 0):
        raise ValueError("Downtime hour bands must divide 24")
    if c.BUSY_PEER_THRESHOLD is not None and not 0 <= c.BUSY_PEER_THRESHOLD <= 1:
        raise ValueError("Busy-peer threshold must be an occupancy fraction in [0,1]")
    if min(c.MIN_OTHER_BANK_PEERS,c.MIN_HEALTHY_MATCHED_HOURS,c.DOWNTIME_REFERENCE_DAYS,
           c.DOWNTIME_VALIDATION_SAMPLE_SIZE,c.DOWNTIME_MIN_VALIDATION_CASES) <= 0:
        raise ValueError("Downtime coverage and validation settings must be positive")
    con.execute("""CREATE TABLE staging.downtime_settings AS SELECT
      ?::BIGINT AS band_hours,?::BIGINT AS stabilization_days,?::BIGINT AS min_peers,
      ?::BIGINT AS min_reference_hours,?::DOUBLE AS busy_threshold,?::BIGINT AS zero_run_hours,
      ?::BIGINT AS min_validation,?::DOUBLE AS error_quantile""", [
        c.DOWNTIME_HOUR_BAND_HOURS,c.DOWNTIME_STABILIZATION_DAYS,c.MIN_OTHER_BANK_PEERS,
        c.MIN_HEALTHY_MATCHED_HOURS,c.BUSY_PEER_THRESHOLD,c.HIDDEN_DOWNTIME_CONSECUTIVE_HOURS,
        c.DOWNTIME_MIN_VALIDATION_CASES,c.DOWNTIME_ERROR_QUANTILE])
    replacements = {
        "{{reference_days}}": str(int(c.DOWNTIME_REFERENCE_DAYS)),
        "{{context_days}}": str(int(c.DOWNTIME_TICKET_CONTEXT_DAYS)),
        "{{sample_size}}": str(int(c.DOWNTIME_VALIDATION_SAMPLE_SIZE)),
        "{{seed}}": str(int(c.RANDOM_SEED)),
        "{{error_quantile}}": str(float(c.DOWNTIME_ERROR_QUANTILE)),
        "{{planned_types}}": ",".join("'" + t.replace("'", "''") + "'" for t in c.PLANNED_OPERATION_TYPES),
    }
    root = Path(__file__).resolve().parents[3] / "sql"
    for path in (root/"staging"/"tickets.sql",root/"staging"/"machine_hourly.sql",
                 root/"marts"/"tickets.sql",root/"marts"/"downtime_hourly.sql"):
        sql = path.read_text(encoding="utf-8")
        for key,value in replacements.items():
            sql = sql.replace(key,value)
        con.execute(sql)


def validate_downtime(con):
    checks = [check for contract in CONTRACTS for check in validate_contract(con,contract)]
    queries = {
        "hour_coverage": """SELECT abs((SELECT count(*) FROM marts.mart_downtime_hourly)-
          (SELECT count(*) FROM raw.machine_hour h CROSS JOIN staging.analysis_window w
            WHERE h.gaming_date BETWEEN w.start_date AND w.end_date))""",
        "placement_identity": """SELECT count(*) FROM staging.hourly_base
          WHERE location_id IS DISTINCT FROM source_location_id OR placement_id IS NULL
            OR gaming_date IS DISTINCT FROM staging.gaming_date(hour_start_utc)""",
        "durations_and_partition": """SELECT count(*) FROM marts.mart_downtime_hourly WHERE
          scheduled_seconds NOT BETWEEN 1 AND 3600 OR available_seconds NOT BETWEEN 0 AND scheduled_seconds
          OR occupied_seconds NOT BETWEEN 0 AND available_seconds
          OR downtime_seconds<>scheduled_seconds-available_seconds
          OR fault_downtime_seconds<0 OR planned_downtime_seconds<0 OR other_downtime_seconds<0
          OR downtime_seconds<>fault_downtime_seconds+planned_downtime_seconds+other_downtime_seconds""",
        "daily_reconciliation": """WITH h AS (SELECT machine_id,gaming_date,
          sum(scheduled_seconds) AS scheduled,sum(available_seconds) AS available,sum(occupied_seconds) AS occupied,
          sum(coin_in_usd) AS coin,sum(payout_usd) AS payout,sum(theo_usd) AS theo,count(*) AS n
          FROM marts.mart_downtime_hourly GROUP BY machine_id,gaming_date)
          SELECT count(*) FROM h FULL JOIN marts.mart_machine_daily d USING(machine_id,gaming_date)
          WHERE h.machine_id IS NULL OR d.machine_id IS NULL OR h.scheduled<>d.scheduled_seconds
            OR h.available<>d.available_seconds OR h.occupied<>d.occupied_seconds
            OR h.coin<>d.coin_in_usd OR h.payout<>d.payout_usd OR abs(h.theo-d.theo_usd)>(h.n+1)*0.00000001""",
        "ticket_times": """SELECT count(*) FROM marts.mart_tickets WHERE response_hours<0 OR repair_hours<0
          OR total_outage_hours<0 OR (response_hours IS NOT NULL AND repair_hours IS NOT NULL
          AND abs(response_hours+repair_hours-total_outage_hours)>0.00000001)""",
        "ticket_coverage": "SELECT abs((SELECT count(*) FROM marts.mart_tickets)-(SELECT count(*) FROM staging.operation_intervals))",
        "estimates": """SELECT count(*) FROM marts.mart_downtime_hourly WHERE estimated_lost_coin_in_usd<0
          OR estimated_lost_theo_usd<0 OR lost_theo_low_usd<0 OR lost_theo_high_usd<lost_theo_low_usd
          OR (downtime_seconds=0 AND (estimated_lost_coin_in_usd IS DISTINCT FROM 0
            OR estimated_lost_theo_usd IS DISTINCT FROM 0))
          OR (estimate_status='estimated' AND (estimated_lost_theo_usd IS NULL OR usual_rate_ratio IS NULL))""",
        "fake_outage_coverage": """SELECT count(*) FROM diagnostics.downtime_validation_cases
          CROSS JOIN staging.downtime_settings s WHERE reference_hours<s.min_reference_hours
          OR neighbor_count<s.min_peers OR actual_theo_usd IS NULL OR predicted_theo_usd IS NULL""",
    }
    checks.extend(check_query(con,"downtime."+name,sql) for name,sql in queries.items())
    return checks
