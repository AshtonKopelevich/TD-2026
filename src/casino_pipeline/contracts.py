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
SOURCE_CONTRACTS = tuple(
    SourceContract(name, f"{folder}/{name}.parquet", KEYS.get(name, ()), REQUIRED_TYPES.get(name, {}))
    for folder, names in GROUPS.items() for name in names
)
