"""Stage-one source contracts. Mart schemas will be added with each mart.

All 31 required tables are explicit. Keys are asserted only where the supplied
dictionary declares them. Column/type checks are a minimum contract, not a claim
that all source schemas have already been frozen.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceContract:
    name: str
    relative_path: str
    key: tuple[str, ...] = ()
    required_types: dict[str, str] = field(default_factory=dict)


GROUPS = {
    "1_prepared_views": ["player_period", "prepared_daily_view", "property_day"],
    "2_machine_decision": ["action_catalog", "calendar_day", "cost_rules", "floor_locations",
                           "floor_walkways", "game_math", "machine_day", "machines", "operations", "placements"],
    "3_guests": ["fnb_transactions", "loyalty_ledger", "players", "sessions", "trips"],
    "4_context": ["events", "zone_traffic_hourly"],
    "4_context/real_sources": ["benchmark_property_monthly", "benchmark_public", "benchmark_state_monthly",
                               "city_visitation_monthly", "visitor_profile_segments", "visitor_profile_summary", "weather_daily"],
    "5_optional": ["machine_hour", "security_incidents", "shift_roster", "visitor_profile_monthly"],
}
KEYS = {
    "player_period": ("player_id", "period_month"),
    "prepared_daily_view": ("machine_id", "gaming_date"),
    "property_day": ("gaming_date",), "action_catalog": ("action_type_id",),
    "calendar_day": ("gaming_date",), "cost_rules": ("cost_rule_id",),
    "floor_locations": ("location_id",), "floor_walkways": ("walkway_id",),
    "game_math": ("config_id",), "machine_day": ("machine_id", "gaming_date"),
    "machines": ("machine_id",), "operations": ("operation_id",),
    "placements": ("placement_id",), "fnb_transactions": ("transaction_id",),
    "loyalty_ledger": ("loyalty_event_id",), "players": ("player_id",),
    "sessions": ("session_segment_id",), "trips": ("observed_visit_id",),
    "events": ("event_id",), "zone_traffic_hourly": ("sensor_id", "hour_start_utc"),
    "machine_hour": ("machine_id", "hour_start_utc"), "security_incidents": ("incident_id",),
    "shift_roster": ("assignment_id",), "visitor_profile_monthly": ("month", "survey_metric"),
}
REQUIRED_TYPES = {
    "prepared_daily_view": {"machine_id": "VARCHAR", "gaming_date": "DATE", "active": "BOOLEAN",
                            "available_hours": "DOUBLE", "coin_in_usd": "DECIMAL(18,2)", "theo_usd": "DECIMAL(18,4)"},
    "machine_day": {"gaming_date": "DATE", "active": "BOOLEAN", "scheduled_seconds": "BIGINT",
                    "coin_in_cents": "BIGINT", "sum_bet_squared": "DOUBLE"},
    "calendar_day": {"gaming_date": "DATE", "scheduled_seconds": "BIGINT"},
    "game_math": {"config_id": "VARCHAR", "payout_multiplier_variance": "DECIMAL(18,8)"},
    "floor_locations": {"location_id": "VARCHAR", "x_m": "DOUBLE", "y_m": "DOUBLE"},
    "placements": {"machine_id": "VARCHAR", "effective_from_utc": "TIMESTAMP", "effective_to_utc": "TIMESTAMP"},
}
# Stage-two inputs: every column used by the machine-day transformation is required.
REQUIRED_TYPES["machine_day"].update({
    **dict.fromkeys("machine_id location_id config_id meter_status".split(), "VARCHAR"),
    **dict.fromkeys("available_seconds occupied_seconds paid_spins carded_spins payout_cents house_win_cents carded_coin_in_cents carded_payout_cents".split(), "BIGINT"),
    "theo_cents": "DECIMAL(24,8)", "carded_theo_cents": "DECIMAL(24,8)",
})
REQUIRED_TYPES["prepared_daily_view"].update({
    **dict.fromkeys("location_id config_id zone_name".split(), "VARCHAR"),
    **dict.fromkeys("payout_usd house_win_usd lease_cost_usd service_cost_usd power_cost_usd repair_cost_usd contribution_after_supplied_costs_usd".split(), "DECIMAL(18,2)"),
    "occupied_hours": "DOUBLE", "faults_opened": "BIGINT",
})
REQUIRED_TYPES["calendar_day"].update(dict.fromkeys("gaming_day_start_utc gaming_day_end_utc".split(), "TIMESTAMP"))
REQUIRED_TYPES["game_math"].update({"configured_rtp": "DECIMAL(10,8)", "theme": "VARCHAR", "volatility_class": "VARCHAR"})
REQUIRED_TYPES["floor_locations"].update(dict.fromkeys("zone_id bank_id node_type".split(), "VARCHAR"))
REQUIRED_TYPES["machines"] = dict.fromkeys("machine_id manufacturer lease_class".split(), "VARCHAR")
REQUIRED_TYPES["placements"].update(dict.fromkeys("placement_id location_id config_id".split(), "VARCHAR"))

# Stage-three descriptive/context inputs. Semantic mapping is documented in methodology.md.
REQUIRED_TYPES["calendar_day"].update({"federal_holiday": "VARCHAR"})
REQUIRED_TYPES["floor_locations"].update({"name": "VARCHAR"})
REQUIRED_TYPES["property_day"] = {
    "gaming_date": "DATE", "active_machines": "BIGINT", "theo_usd": "DECIMAL(18,4)",
    "available_machine_hours": "DOUBLE", "occupied_machine_hours": "DOUBLE",
    **dict.fromkeys("coin_in_usd payout_usd house_win_usd pos_cash_usd pos_cogs_usd comp_cost_usd machine_supplied_costs_usd tech_labor_cost_usd contribution_after_supplied_costs_usd".split(), "DECIMAL(18,2)"),
}
REQUIRED_TYPES["events"] = {"event_id": "VARCHAR", "name": "VARCHAR", "start_date": "DATE", "end_date": "DATE"}
REQUIRED_TYPES["zone_traffic_hourly"] = {
    **dict.fromkeys("sensor_id zone_id counter_status".split(), "VARCHAR"),
    "hour_start_utc": "TIMESTAMP", "entries_count": "BIGINT", "coverage_minutes": "INTEGER",
}
REQUIRED_TYPES["weather_daily"] = {
    "station_id": "VARCHAR", "source_date": "DATE", "tmax_c": "DECIMAL(8,1)", "prcp_mm": "DECIMAL(8,1)",
    **dict.fromkeys("tmax_qflag prcp_qflag prcp_mflag".split(), "VARCHAR"),
}
REQUIRED_TYPES["benchmark_state_monthly"] = {
    "month": "VARCHAR", "handle_usd": "DECIMAL(24,2)", "agr_usd": "DECIMAL(24,2)",
    "source_url": "VARCHAR", "retrieved_date": "DATE",
}
REQUIRED_TYPES["city_visitation_monthly"] = {
    **dict.fromkeys("month source_url source_revision as_of_limitation".split(), "VARCHAR"), "visitor_volume": "BIGINT",
}

# Stage-four guest accounting inputs (opaque IDs remain text).
REQUIRED_TYPES["players"] = {
    **dict.fromkeys("player_id home_region age_band opening_tier".split(), "VARCHAR"),
    "enrolled_at_utc": "TIMESTAMP",
}
REQUIRED_TYPES["sessions"] = {
    **dict.fromkeys("player_id observed_visit_id logical_session_id session_segment_id".split(), "VARCHAR"),
    "gaming_date": "DATE", "start_utc": "TIMESTAMP", "end_utc": "TIMESTAMP",
    "coin_in_cents": "BIGINT", "payout_cents": "BIGINT", "theo_cents": "DECIMAL(24,8)",
}
REQUIRED_TYPES["trips"] = {
    "observed_visit_id": "VARCHAR", "player_id": "VARCHAR", "first_observed_at_utc": "TIMESTAMP", "observation_complete": "BOOLEAN",
}
REQUIRED_TYPES["fnb_transactions"] = {
    **dict.fromkeys("transaction_id player_id observed_visit_id comp_id".split(), "VARCHAR"),
    "event_at_utc": "TIMESTAMP",
    **dict.fromkeys("cash_receipt_cents cogs_cents face_value_cents".split(), "BIGINT"),
}
REQUIRED_TYPES["loyalty_ledger"] = {
    **dict.fromkeys("loyalty_event_id player_id event_type redeemed_pos_id".split(), "VARCHAR"),
    "event_at_utc": "TIMESTAMP",
    **dict.fromkeys("points_delta economic_cost_cents face_value_cents".split(), "BIGINT"),
}
REQUIRED_TYPES["player_period"] = {
    **dict.fromkeys("player_id period_month home_region age_band opening_tier tier_end".split(), "VARCHAR"),
    **dict.fromkeys("observed_visits incomplete_visits sessions comps_redeemed points_earned points_redeemed".split(), "BIGINT"),
    "carded_play_hours": "DOUBLE", "theo_usd": "DECIMAL(18,4)", "luck_residual_usd": "DECIMAL(18,4)",
    **dict.fromkeys("tracked_coin_in_usd tracked_payout_usd tracked_net_usd linked_pos_cash_usd linked_pos_cogs_usd comp_face_value_usd comp_cost_usd tracked_contribution_usd".split(), "DECIMAL(18,2)"),
}

# Stage-five hourly and operations inputs.
REQUIRED_TYPES["machines"]["install_date"] = "DATE"
REQUIRED_TYPES["operations"] = {
    **dict.fromkeys("operation_id machine_id location_id event_type".split(), "VARCHAR"),
    **dict.fromkeys("opened_at_utc recorded_at_utc work_started_at_utc available_at_utc".split(), "TIMESTAMP"),
    "direct_cost_cents": "BIGINT",
}
REQUIRED_TYPES["machine_hour"] = {
    **dict.fromkeys("machine_id location_id utc_offset".split(), "VARCHAR"), "hour_start_utc": "TIMESTAMP",
    "gaming_date": "DATE", "local_hour": "INTEGER", "active": "BOOLEAN",
    **dict.fromkeys("available_seconds occupied_seconds paid_spins coin_in_cents payout_cents".split(), "BIGINT"),
}
REQUIRED_TYPES["shift_roster"] = {
    **dict.fromkeys("assignment_id role zone_id".split(), "VARCHAR"), "gaming_date": "DATE",
    "start_utc": "TIMESTAMP", "end_utc": "TIMESTAMP",
}

# Stage-seven calendar features, catalogue pricing and target scopes.
REQUIRED_TYPES['events'].update({'announced_date':'DATE','local_scope':'VARCHAR'})
REQUIRED_TYPES['shift_roster']['shift'] = 'VARCHAR'
REQUIRED_TYPES['action_catalog'] = {
    **dict.fromkeys('action_type_id name unit incompatibility_group notes'.split(),'VARCHAR'),
    'unit_cost_cents':'BIGINT','recurring_cost_cents_per_day':'BIGINT',
    **dict.fromkeys('lead_days downtime_minutes quantity_limit'.split(),'INTEGER'),
}

SOURCE_CONTRACTS = tuple(
    SourceContract(name, f"{folder}/{name}.parquet", KEYS.get(name, ()), REQUIRED_TYPES.get(name, {}))
    for folder, names in GROUPS.items() for name in names
)
