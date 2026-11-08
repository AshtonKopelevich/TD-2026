"""Display vocabulary for the codes defined in docs/mart_contracts.md.

If the contract's codes change (classification labels, event types, action ids), this is
the one file to update.
"""
from __future__ import annotations

UNDERPERFORMANCE_INDICATORS = [
    ('low_earnings', 'Low actual earnings', 'Actual house win/hour below zone peers; at least 14 peer-covered days and 80% available-hour coverage.'),
    ('low_demand', 'Low wagering demand', 'Among below-peer earners: wagering/hour more than 20% below zone peers.'),
    ('persistent', 'Persistent shortfall', 'Among below-peer earners: lower actual earnings in at least 3 months and two-thirds of measured months. A measured month needs 7 peer-covered days.'),
    ('low_availability', 'Low availability', 'Among below-peer earners: more than 5% of scheduled time unavailable.'),
    ('repair_change', 'Repair-related change', 'Among below-peer earners: actual earnings/hour changed by at least 20% around a comparable repair; seven complete dates on each side.'),
]

# primary_classification -> (label, betting spot on the opening page, plain-English cause)
CLASSES = {
    "luck_compatible":       ("Luck",            "Luck",         "bad luck"),
    "location_associated":   ("Location",        "Location",     "where they sit on the floor"),
    "downtime_associated":   ("Downtime",        "Downtime",     "downtime"),
    "repair_associated":     ("Repairs",         "Repairs",      "faults since repaired"),
    "hold_inspection_lead":  ("Hold gap",        "Hold gap",     "a hold gap worth inspecting"),
    "weak_demand_candidate": ("Weak machine",    "Weak machine", "weak demand for the game itself"),
    "no_clear_issue":        ("No clear cause",  "Unclear",      "nothing we can find"),
    "mixed_evidence":        ("Mixed evidence",  "Unclear",      "several overlapping causes"),
    "insufficient_evidence": ("Too little data", "Unclear",      "too little data to say"),
}
# Betting spots, left to right: causes outside the machine, then the machine itself.
SPOTS = ["Luck", "Location", "Downtime", "Repairs", "Hold gap", "Weak machine", "Unclear"]
SPOT_NOTES = {
    "Luck": "Paid out more than its game math expects, within normal swings.",
    "Location": "Earns like its neighbours; the spot is quiet.",
    "Downtime": "Lost play while it was broken or switched off.",
    "Repairs": "Recovered after a fault was fixed.",
    "Hold gap": "Holds less than its settings promise. Inspect it.",
    "Weak machine": "Players pass it by in a busy spot. Replace it.",
    "Unclear": "No adjustment explains it, or the evidence is mixed.",
}
# Which spots mean the machine itself is the problem.
MACHINE_SPOTS = {"Hold gap", "Weak machine"}

# Evidence flags on the scorecard, grouped by what they imply.
FLAGS_NOT_MACHINE = [("location_flag", "Location"), ("downtime_flag", "Downtime"),
                     ("repair_rebound_flag", "Repair rebound"), ("luck_compatible", "Luck plausible")]
FLAGS_MACHINE = [("weak_demand_flag", "Weak demand"), ("hold_anomaly_flag", "Hold gap")]

# The action each cause points to (from the team plan's budget framework).
CAUSE_ACTION = {
    "luck_compatible": "keep the budget: luck evens out on its own",
    "location_associated": "move machines or improve the zone, not replace them",
    "downtime_associated": "add a technician or schedule preventive maintenance",
    "repair_associated": "schedule preventive maintenance for that manufacturer",
    "hold_inspection_lead": "inspect and verify the payout settings",
    "weak_demand_candidate": "replace them, preferably with leased machines",
    "no_clear_issue": "leave them alone",
    "mixed_evidence": "gather more evidence before spending",
    "insufficient_evidence": "gather more evidence before spending",
}

EVENT_TYPES = {"fault_repair": "Fault repair", "scheduled_maintenance": "Planned maintenance",
               "move": "Move", "install": "Install", "retire": "Retire"}

# Shift boundaries in local clock hours (from the source shift_roster: day starts 06:00).
SHIFTS = [("Day", 6, 14), ("Swing", 14, 22), ("Grave", 22, 30)]


def shift_of(local_hour: int) -> str:
    h = local_hour if local_hour >= 6 else local_hour + 24
    return next(name for name, a, b in SHIFTS if a <= h < b)


# Short names for charts; the full name comes from the source action_catalog when present.
ACTION_SHORT = {
    "A-MOVE-MACHINE": "Move machines", "A-MOVE-BANK": "Move a bank",
    "A-REPLACE-LEASE": "Replace (lease)", "A-REPLACE-BUY": "Replace (buy)",
    "A-TECH-SHIFT": "Add a technician", "A-PREVENTIVE": "Preventive maintenance",
    "A-INSPECT": "Inspect machines", "A-WAYFINDING": "Zone signage",
    "A-COMP-PILOT": "Comp pilot", "A-COMP-CHANGE": "Comp rate change",
    "A-PROMO": "Promotion weekend", "A-SURVEY": "Guest survey", "A-KEEP": "Keep the budget",
}

# Which chapter presents each mart, for "trace this back to its evidence" links.
MART_CHAPTER = {
    "mart_machine_scorecard": "verdict", "mart_machine_month": "machines", "mart_machine_daily": "machines",
    "mart_floor_daily": "demand", "mart_zone_daily": "demand", "mart_visits_month": "demand",
    "mart_benchmark_month": "demand", "mart_downtime_hourly": "downtime", "mart_tickets": "downtime",
    "mart_player_month": "guests", "mart_comps_tier_month": "guests", "mart_comps_daily": "guests",
    "mart_forecast": "forecast", "mart_actions": "plan",
}

BUDGET = 100_000
MAX_ACTION_TYPES = 3
