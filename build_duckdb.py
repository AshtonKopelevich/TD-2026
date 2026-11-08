"""
Build the PLACEHOLDER database the dashboard reads: casino.duckdb, schema `marts`.

    python build_duckdb.py
    python build_duckdb.py --placeholder marts_placeholder --db casino.duckdb

The numbers are fake (from marts_placeholder/*.csv). What this script gets right is the
SHAPE: every table is reshaped into the column names, types and grain of
docs/mart_contracts.md, so the dashboard is written against the contract. The real
pipeline writes the same tables to output/casino.duckdb, and the dashboard picks that file
up automatically with no code changes.

To make the template look like the real floor, placeholder dimensions are mapped onto the
real source dimensions: zones A-F become the real zones with real slot coordinates
(floor_locations), and manufacturers, tiers and home regions use the real names.

A marker table, marts._placeholder, tells the dashboard to show its "placeholder data"
banner. The real build won't have it.

Simplifications versus the contract (fine for a template, not for analysis):
  - mart_downtime_hourly holds only machine-hours with downtime or a hidden-downtime flag;
    the real mart has every installed machine-hour (zero rows add nothing to the sums the
    dashboard uses).
  - Statistical columns (z, p, q, bootstrap) are derived from the placeholder's fake
    z-scores, not computed.
"""
from __future__ import annotations

import argparse
import math
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dashboard-royale-main" / "data"
rng = np.random.default_rng(2025)

# ---- placeholder -> real dimension maps ------------------------------------------------
ZONE_MAP = {"A": "Z-PIT", "B": "Z-BAR", "C": "Z-ENT", "D": "Z-HTL", "E": "Z-GAR", "F": "Z-B40"}
OVERFLOW_ZONES = ["Z-HL", "Z-PIT", "Z-BAR", "Z-B40", "Z-ENT", "Z-HTL", "Z-GAR"]
ZONE_NAMES = {"Z-PIT": "Center Pit", "Z-BAR": "Bar Row", "Z-ENT": "Main Entrance",
              "Z-HTL": "Hotel Corridor", "Z-GAR": "Garage Entrance", "Z-B40": "Back Forty",
              "Z-HL": "High-Limit Room"}
MFR_MAP = {"Aristo": "Halcyon", "Brightline": "Ridgeline", "Corvane": "Northwind"}
CONFIG_MAP = {"GS01": ("G-JKP88", "Jackpot Summit"), "GS02": ("G-PEN89", "Prairie Thunder"),
              "GS03": ("G-STD90", "Desert Gold"), "GS04": ("G-HL90", "Platinum Reels"),
              "GS05": ("G-NEW91", "Aurora Link"), "GS06": ("G-LOW92", "Lucky Lanterns"),
              "GS07": ("G-HIGH92", "Comet Cash"), "GS08": ("G-CLS93", "Classic Sevens"),
              "GS09": ("G-NEO88", "Neon Nights"), "GS10": ("G-VID95", "Royal Draw")}
TIER_MAP = {"Bronze": "Base", "Silver": "Base", "Gold": "Gold", "Platinum": "Platinum"}
REGION_MAP = {"Local": "Local", "California": "Regional", "Other US": "Domestic",
              "International": "International"}
CLASS_MAP = {"Weak demand": "weak_demand_candidate", "Held back by location": "location_associated",
             "Held back by downtime": "downtime_associated", "Faulty while running": "repair_associated",
             "Hold anomaly": "hold_inspection_lead", "Unlucky": "luck_compatible",
             "Performing normally": "no_clear_issue"}
EVENT_MAP = {"Fault": "fault_repair", "Planned maintenance": "scheduled_maintenance",
             "Move": "move", "Install": "install"}
SHIFT_START = {"Day": 6, "Swing": 14, "Grave": 22}          # local clock hour
HOLIDAYS = {"2025-01-01": "New Year's Day", "2025-01-20": "Martin Luther King Jr. Day",
            "2025-02-17": "Presidents' Day", "2025-05-26": "Memorial Day"}
DST_START_LOCAL = datetime(2025, 3, 9, 2)                     # spring forward (America/Los_Angeles)


def to_utc(local: pd.Series) -> pd.Series:
    """America/Los_Angeles wall time -> naive UTC (2025 has one DST change in range)."""
    return local + pd.to_timedelta(np.where(local >= DST_START_LOCAL, 7, 8), unit="h")


def month_start(d: pd.Series) -> pd.Series:
    return pd.to_datetime(d).dt.to_period("M").dt.start_time


def safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b == 0, 1, b), np.nan)


def bh_qvalues(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values (NaN-safe)."""
    valid = p.dropna()
    n = len(valid)
    order = valid.sort_values()
    ranked = order * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1].clip(upper=1)
    return q.reindex(p.index)


def load_placeholder(folder: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for csv in sorted(folder.glob("mart_*.csv")):
        out[csv.stem] = pd.read_csv(csv)
    return out


# =========================================================================================
def assign_slots(machines: pd.DataFrame, theo_by_machine: pd.Series) -> pd.DataFrame:
    """Map each placeholder machine onto a real slot (location_id, zone, bank, x, y)."""
    slots = duckdb.sql(f"""
        SELECT location_id, zone_id, bank_id, x_m, y_m
        FROM '{(SOURCE / '2_machine_decision/floor_locations.parquet').as_posix()}'
        WHERE node_type = 'slot' ORDER BY zone_id, bank_id, location_id""").df()
    free = {z: deque(g.to_dict("records")) for z, g in slots.groupby("zone_id")}
    rows, overflow = [], []
    for zone, g in machines.groupby("zone"):
        # Highest earners overflow first (to the high-limit room), keeping weak machines in place.
        order = g.assign(theo=g.machine_id.map(theo_by_machine)).sort_values("theo")
        for m in order.machine_id:
            q = free[ZONE_MAP[zone]]
            (rows if q else overflow).append((m, q.popleft()) if q else m)
    for m in overflow:
        z = next(z for z in OVERFLOW_ZONES if free[z])
        rows.append((m, free[z].popleft()))
    return pd.DataFrame([{"machine_id": m, **s} for m, s in rows])


def build_machine_daily(ph, tickets_raw) -> pd.DataFrame:
    d = ph["mart_machine_daily"].copy()
    d["gaming_date"] = pd.to_datetime(d.gaming_date)
    machines = d.groupby("machine_id").agg(zone=("zone", "first")).reset_index()
    slots = assign_slots(machines, d.groupby("machine_id").theo_usd.sum())
    d = d.merge(slots, on="machine_id")

    num = d.machine_id.str[1:].astype(int)
    d["manufacturer"] = d.manufacturer.map(MFR_MAP).fillna(
        pd.Series(np.where(num % 2 == 0, "Ridgeline", "Northwind"), index=d.index))
    d["config_id"] = d.game_setting.map(lambda g: CONFIG_MAP[g][0])
    d["theme"] = d.game_setting.map(lambda g: CONFIG_MAP[g][1])
    d["zone_name"] = d.zone_id.map(ZONE_NAMES)
    d["lease_class"] = np.where(num % 3 == 0, "leased", "owned")
    d["volatility_class"] = d.volatility.str.lower()
    d["month_start"] = month_start(d.gaming_date)

    cal = np.where(d.gaming_date == "2025-03-08", 82_800, 86_400)
    d["calendar_day_seconds"] = cal
    d["scheduled_seconds"] = np.minimum((d.scheduled_hours * 3600).round(), cal).astype("int64")
    d["available_seconds"] = np.minimum((d.available_hours * 3600).round(), d.scheduled_seconds).astype("int64")
    per_hr = safe_div(d.coin_in_usd, d.available_seconds / 3600)
    occ = np.clip(np.nan_to_num(per_hr) / 1500, 0.02, 0.9)
    d["occupied_seconds"] = (d.available_seconds * occ).round().astype("int64")

    share = np.clip(rng.beta(6, 4, len(d)) + d.machine_id.map(
        dict(zip(machines.machine_id, rng.normal(0, 0.05, len(machines))))), 0.2, 0.9)
    d["paid_spins"] = (d.coin_in_usd / 1.2).round().astype("int64")
    d["carded_spins"] = (d.paid_spins * share).round().astype("int64")
    d["carded_coin_in_usd"] = (d.coin_in_usd * share).round(2)
    d["carded_payout_usd"] = (d.payout_usd * share).round(2)
    d["carded_theo_usd"] = d.theo_usd * share
    d["luck_residual_usd"] = d.house_win_usd - d.theo_usd

    for col, frac in [("lease_cost_usd", 0.45), ("service_cost_usd", 0.30),
                      ("power_cost_usd", 0.20), ("repair_cost_usd", 0.05)]:
        d[col] = (d.machine_cost_usd * frac).round(2)
    d["machine_cost_usd"] = d[["lease_cost_usd", "service_cost_usd", "power_cost_usd", "repair_cost_usd"]].sum(axis=1)
    d["actual_contribution_usd"] = d.house_win_usd - d.machine_cost_usd
    d["expected_contribution_usd"] = d.theo_usd - d.machine_cost_usd

    avail_h = d.available_seconds / 3600
    d["availability_ratio"] = safe_div(d.available_seconds, d.scheduled_seconds)
    d["occupancy_ratio"] = safe_div(d.occupied_seconds, d.available_seconds)
    d["observed_hold"] = safe_div(d.house_win_usd, d.coin_in_usd)
    d["expected_hold"] = safe_div(d.theo_usd, d.coin_in_usd)
    d["carded_coin_in_share"] = safe_div(d.carded_coin_in_usd, d.coin_in_usd)
    d["coin_in_per_available_hour"] = safe_div(d.coin_in_usd, avail_h)
    d["theo_per_available_hour"] = safe_div(d.theo_usd, avail_h)
    d["expected_contribution_per_available_hour"] = safe_div(d.expected_contribution_usd, avail_h)
    d["configured_rtp"] = 1 - d.groupby("config_id").theo_usd.transform("sum") / d.groupby("config_id").coin_in_usd.transform("sum")
    d["active"] = True
    d["meter_status"] = "ok"
    d["payout_multiplier_variance"] = np.nan
    d["sum_bet_squared_cents2"] = np.nan
    d["outcome_variance_usd2"] = np.nan

    faults = tickets_raw[tickets_raw.ticket_type == "Fault"].groupby(
        ["machine_id", pd.to_datetime(tickets_raw.opened_gaming_date)]).size()
    faults.index.names = ["machine_id", "gaming_date"]
    d = d.merge(faults.rename("faults_opened").reset_index(), on=["machine_id", "gaming_date"], how="left")
    d["faults_opened"] = d.faults_opened.fillna(0).astype("int64")

    cols = ["gaming_date", "month_start", "machine_id", "location_id", "zone_id", "bank_id", "config_id",
            "zone_name", "manufacturer", "theme", "lease_class", "x_m", "y_m",
            "scheduled_seconds", "available_seconds", "occupied_seconds", "paid_spins", "carded_spins",
            "coin_in_usd", "payout_usd", "house_win_usd", "carded_coin_in_usd", "carded_payout_usd",
            "theo_usd", "carded_theo_usd", "luck_residual_usd", "lease_cost_usd", "service_cost_usd",
            "power_cost_usd", "repair_cost_usd", "machine_cost_usd", "actual_contribution_usd",
            "expected_contribution_usd", "availability_ratio", "occupancy_ratio", "observed_hold",
            "expected_hold", "carded_coin_in_share", "coin_in_per_available_hour", "theo_per_available_hour",
            "expected_contribution_per_available_hour", "active", "meter_status", "calendar_day_seconds",
            "configured_rtp", "volatility_class", "payout_multiplier_variance", "sum_bet_squared_cents2",
            "outcome_variance_usd2", "faults_opened"]
    return d[cols]


M_SUM = ["scheduled_seconds", "available_seconds", "occupied_seconds", "paid_spins", "carded_spins",
         "coin_in_usd", "payout_usd", "house_win_usd", "carded_coin_in_usd", "carded_payout_usd", "theo_usd",
         "carded_theo_usd", "luck_residual_usd", "lease_cost_usd", "service_cost_usd", "power_cost_usd",
         "repair_cost_usd", "machine_cost_usd", "actual_contribution_usd", "expected_contribution_usd"]


def add_ratios(g: pd.DataFrame) -> pd.DataFrame:
    avail_h = g.available_seconds / 3600
    g["availability_ratio"] = safe_div(g.available_seconds, g.scheduled_seconds)
    g["occupancy_ratio"] = safe_div(g.occupied_seconds, g.available_seconds)
    g["observed_hold"] = safe_div(g.house_win_usd, g.coin_in_usd)
    g["expected_hold"] = safe_div(g.theo_usd, g.coin_in_usd)
    g["carded_coin_in_share"] = safe_div(g.carded_coin_in_usd, g.coin_in_usd)
    g["coin_in_per_available_hour"] = safe_div(g.coin_in_usd, avail_h)
    g["theo_per_available_hour"] = safe_div(g.theo_usd, avail_h)
    g["expected_contribution_per_available_hour"] = safe_div(g.expected_contribution_usd, avail_h)
    return g


def p_from_z(z: pd.Series) -> pd.Series:
    return z.abs().map(lambda v: math.erfc(v / math.sqrt(2)) if pd.notna(v) else np.nan)


def build_machine_month(daily, ph) -> pd.DataFrame:
    g = daily.groupby(["machine_id", "month_start"]).agg(
        period_start=("gaming_date", "min"), period_end=("gaming_date", "max"),
        active_days=("gaming_date", "count"), manufacturer=("manufacturer", "first"),
        lease_class=("lease_class", "first"), location_count=("location_id", "nunique"),
        config_count=("config_id", "nunique"), **{c: (c, "sum") for c in M_SUM}).reset_index()
    g = add_ratios(g)
    z = ph["mart_machine_month"][["machine_id", "month", "z_score"]].copy()
    z["month_start"] = pd.to_datetime(z.month + "-01")
    g = g.merge(z[["machine_id", "month_start", "z_score"]], on=["machine_id", "month_start"], how="left")
    g = g.rename(columns={"z_score": "luck_z_score"})
    g["luck_p_value"] = p_from_z(g.luck_z_score)
    g["luck_q_value"] = g.groupby("month_start", group_keys=False).luck_p_value.apply(bh_qvalues)
    g["bootstrap_hold_gap_low"] = np.nan
    g["bootstrap_hold_gap_high"] = np.nan
    g["statistical_status"] = "ok_no_bootstrap"
    return g


def build_scorecard(daily, ph) -> pd.DataFrame:
    g = daily.groupby("machine_id").agg(
        analysis_start=("gaming_date", "min"), analysis_end=("gaming_date", "max"),
        active_days=("gaming_date", "count"), **{c: (c, "sum") for c in M_SUM}).reset_index()
    g = add_ratios(g)
    g["analysis_start"] = pd.Timestamp("2025-01-01")
    g["analysis_end"] = pd.Timestamp("2025-06-30")

    for col, by in [("naive_rank", "house_win_usd"), ("adjusted_rank", "expected_contribution_per_available_hour")]:
        order = g.sort_values([by, "machine_id"], na_position="last")
        g.loc[order.index, col] = np.arange(1, len(g) + 1)
        g[col] = g[col].astype("int64")
    g["naive_bottom_10"] = g.naive_rank <= 10

    # Zone peers: other machines in the same zone on the same dates, target excluded.
    zd = daily.groupby(["zone_id", "gaming_date"])[["theo_usd", "available_seconds"]].sum() \
        .rename(columns=lambda c: f"zone_{c}")
    dd = daily.join(zd, on=["zone_id", "gaming_date"])
    dd["peer_theo"] = dd.zone_theo_usd - dd.theo_usd
    dd["peer_avail_h"] = (dd.zone_available_seconds - dd.available_seconds) / 3600
    peer = dd.groupby("machine_id").agg(peer_theo=("peer_theo", "sum"), peer_h=("peer_avail_h", "sum"),
                                        peer_coverage_days=("gaming_date", "count"))
    g = g.join(peer, on="machine_id")
    g["peer_theo_per_hour"] = safe_div(g.peer_theo, g.peer_h)
    g["peer_rate_ratio"] = safe_div(g.theo_per_available_hour, g.peer_theo_per_hour)

    sc = ph["mart_machine_scorecard"].set_index("machine_id")
    g["luck_z_score"] = g.machine_id.map(sc.z_score)
    g["luck_p_value"] = p_from_z(g.luck_z_score)
    g["luck_q_value"] = bh_qvalues(g.luck_p_value)
    g["bootstrap_hold_gap_low"] = g.machine_id.map(sc.boot_low_usd) / g.coin_in_usd
    g["bootstrap_hold_gap_high"] = g.machine_id.map(sc.boot_high_usd) / g.coin_in_usd
    g["bootstrap_replicates"] = 10_000
    g["statistical_status"] = "ok"

    code = g.machine_id.map(sc.classification).map(CLASS_MAP)
    g["primary_classification"] = code
    g["weak_demand_flag"] = code == "weak_demand_candidate"
    g["location_flag"] = code == "location_associated"
    g["downtime_flag"] = code == "downtime_associated"
    g["repair_rebound_flag"] = code == "repair_associated"
    g["hold_anomaly_flag"] = code == "hold_inspection_lead"
    g["luck_compatible"] = (g.bootstrap_hold_gap_low <= 0) & (g.bootstrap_hold_gap_high >= 0) | (code == "luck_compatible")

    zone_of = daily.sort_values("gaming_date").groupby("machine_id").zone_name.last()
    floor_rate = g.theo_usd.sum() / (g.available_seconds.sum() / 3600)
    zone_rate = daily.groupby("zone_name").theo_usd.sum() / (daily.groupby("zone_name").available_seconds.sum() / 3600)

    def reason(r):
        z = zone_of[r.machine_id]
        if r.primary_classification == "weak_demand_candidate":
            return (f"Earns {r.peer_rate_ratio:.0%} of what its {z} neighbours earn per open hour, "
                    f"with {r.availability_ratio:.0%} availability. Players pass it by.")
        if r.primary_classification == "location_associated":
            return (f"Earns {r.peer_rate_ratio:.0%} of its neighbours' rate, in a zone that runs at "
                    f"{zone_rate[z] / floor_rate:.0%} of the floor average: few players reach this corner.")
        if r.primary_classification == "downtime_associated":
            return f"Open only {r.availability_ratio:.0%} of scheduled hours; lost play explains the gap."
        if r.primary_classification == "repair_associated":
            return "Theo per hour recovered after repairs: faults held it back, not the game."
        if r.primary_classification == "hold_inspection_lead":
            return (f"Held {r.observed_hold:.2%} against an expected {r.expected_hold:.2%}. "
                    "A lead to inspect, not proof of a fault.")
        if r.primary_classification == "luck_compatible":
            return f"Won ${-r.luck_residual_usd:,.0f} less than theo, and the luck interval includes zero."
        return "Nothing explains a shortfall; it earns within the normal range."

    g["classification_reason"] = g.apply(reason, axis=1)
    return g.drop(columns=["peer_theo", "peer_h"])


def build_floor_daily(daily, ph, comps_daily) -> pd.DataFrame:
    f = ph["mart_floor_daily"].copy()
    f["gaming_date"] = pd.to_datetime(f.gaming_date)
    agg = daily.groupby("gaming_date").agg(
        active_machines=("machine_id", "nunique"), sched=("scheduled_seconds", "sum"),
        avail=("available_seconds", "sum"), occ=("occupied_seconds", "sum"),
        coin_in_usd=("coin_in_usd", "sum"), payout_usd=("payout_usd", "sum"),
        house_win_usd=("house_win_usd", "sum"), theo_usd=("theo_usd", "sum"),
        carded_coin_in_usd=("carded_coin_in_usd", "sum"), machine_cost_usd=("machine_cost_usd", "sum"))
    out = agg.reset_index()
    out["month_start"] = month_start(out.gaming_date)
    out["weekday_index"] = out.gaming_date.dt.day_of_week
    out["is_weekend"] = out.weekday_index >= 5
    out["federal_holiday"] = out.gaming_date.dt.strftime("%Y-%m-%d").map(HOLIDAYS)
    ev = f.set_index("gaming_date").event_name
    out["events_active"] = out.gaming_date.map(ev).replace("", np.nan)
    out["scheduled_machine_hours"] = out.sched / 3600
    out["available_machine_hours"] = out.avail / 3600
    out["occupied_machine_hours"] = out.occ / 3600
    out["carded_coin_in_share"] = safe_div(out.carded_coin_in_usd, out.coin_in_usd)
    out["coin_in_per_active_machine_day"] = safe_div(out.coin_in_usd, out.active_machines)
    out["pos_cash_usd"] = (out.coin_in_usd * rng.uniform(0.012, 0.018, len(out))).round(2)
    out["comp_cost_usd"] = out.gaming_date.map(comps_daily.set_index("gaming_date").comp_cost_usd).fillna(0)
    out["pos_cogs_usd"] = (out.pos_cash_usd * 0.32 + out.comp_cost_usd).round(2)
    out["tech_labor_cost_usd"] = 3 * 8 * 48.0 * 3
    out["actual_floor_contribution_usd"] = out.house_win_usd + out.pos_cash_usd - out.pos_cogs_usd - out.machine_cost_usd
    temp_f = out.gaming_date.map(f.set_index("gaming_date").max_temp_f)
    out["weather_temperature_max_c"] = ((temp_f - 32) * 5 / 9).round(1)
    out["weather_precipitation_mm"] = (out.gaming_date.map(f.set_index("gaming_date").precip_in) * 25.4).round(1)
    out["weather_status"] = "ok_local_calendar_date"
    return out.drop(columns=["sched", "avail", "occ"])


def build_zone_daily(daily, ph) -> pd.DataFrame:
    z = daily.groupby(["zone_id", "zone_name", "gaming_date", "month_start"]).agg(
        active_machines=("machine_id", "nunique"), scheduled_seconds=("scheduled_seconds", "sum"),
        available_seconds=("available_seconds", "sum"), occupied_seconds=("occupied_seconds", "sum"),
        coin_in_usd=("coin_in_usd", "sum"), house_win_usd=("house_win_usd", "sum"),
        theo_usd=("theo_usd", "sum")).reset_index()
    avail_h = z.available_seconds / 3600
    z["coin_in_per_available_hour"] = safe_div(z.coin_in_usd, avail_h)
    z["theo_per_available_hour"] = safe_div(z.theo_usd, avail_h)

    t = ph["mart_zone_daily"].copy()
    t["zone_id"] = t.zone.map(ZONE_MAP)
    t["gaming_date"] = pd.to_datetime(t.gaming_date)
    hl = t[t.zone_id == "Z-PIT"].assign(zone_id="Z-HL", entries=lambda d: (d.entries * 0.2).round())
    t = pd.concat([t, hl])[["zone_id", "gaming_date", "entries", "counter_hours_online", "counter_hours_expected"]]
    z = z.merge(t, on=["zone_id", "gaming_date"], how="left")
    z["counter_observed_seconds"] = (z.counter_hours_online.fillna(0) * 3600).astype("int64")
    z["counter_expected_seconds"] = (z.counter_hours_expected.fillna(24) * 3600).astype("int64")
    z["entries_observed"] = z.entries.where(z.counter_observed_seconds > 0).astype("Int64")
    z["counter_coverage_ratio"] = safe_div(z.counter_observed_seconds, z.counter_expected_seconds)
    z["traffic_status"] = np.select(
        [z.counter_observed_seconds == 0, z.counter_observed_seconds < z.counter_expected_seconds],
        ["offline", "partial"], "complete")
    return z.drop(columns=["entries", "counter_hours_online", "counter_hours_expected"])


def build_players(ph, comps_tier) -> pd.DataFrame:
    """Synthesise player x month rows that add up to the placeholder's segment totals."""
    pm = ph["mart_player_month"].copy()
    pm["opening_tier"] = pm.tier.map(TIER_MAP)
    pm["home_region"] = pm.home_region.map(REGION_MAP)
    pm["month_start"] = pd.to_datetime(pm.month + "-01")
    cells = pm.groupby(["opening_tier", "age_band", "home_region"])
    frames = []
    for ci, ((tier, age, region), g) in enumerate(cells):
        per_month = g.groupby("month_start").players.sum()
        pool = np.array([f"P{ci:03d}{j:05d}" for j in rng.permutation(per_month.max())])
        for month, mg in g.groupby("month_start"):
            ids = rng.permutation(pool)[: mg.players.sum()]
            start = 0
            for r in mg.itertuples():
                n = r.players
                pid = ids[start: start + n]
                start += n
                w = rng.lognormal(0, 1.3, n)
                w /= w.sum()
                coin = r.coin_in_usd * w
                theo = r.expected_loss_usd * w
                loss = theo + rng.normal(0, 0.12, n) * coin
                loss += (r.net_loss_usd - loss.sum()) * w
                frames.append(pd.DataFrame({
                    "player_id": pid, "month_start": month, "home_region": region, "age_band": age,
                    "opening_tier": tier, "tier_end": tier, "tracked_coin_in_usd": coin,
                    "actual_tracked_loss_usd": loss, "theo_usd": theo}))
    p = pd.concat(frames, ignore_index=True)
    p["tracked_payout_usd"] = p.tracked_coin_in_usd - p.actual_tracked_loss_usd
    p["tracked_net_usd"] = -p.actual_tracked_loss_usd
    p["luck_residual_usd"] = p.tracked_net_usd + p.theo_usd
    n = len(p)
    p["sessions"] = rng.poisson(2.5, n) + 1
    p["observed_visits"] = np.maximum(1, p.sessions // 2)
    p["incomplete_visits"] = rng.binomial(p.observed_visits, 0.04)
    p["carded_play_hours"] = (p.tracked_coin_in_usd / 650).round(2)
    p["linked_pos_cash_usd"] = (p.tracked_coin_in_usd * rng.uniform(0.004, 0.02, n)).round(2)

    # Comp cost and points from the tier-month totals, shared out by theo / coin-in.
    key = ["opening_tier", "month_start"]
    theo_share = p.theo_usd / p.groupby(key).theo_usd.transform("sum")
    coin_share = p.tracked_coin_in_usd / p.groupby(key).tracked_coin_in_usd.transform("sum")
    ct = comps_tier.set_index(key)
    idx = pd.MultiIndex.from_frame(p[key])
    p["comp_cost_usd"] = (theo_share * ct.comp_cost_usd.reindex(idx).values).round(2)
    p["comp_face_value_usd"] = (p.comp_cost_usd * 1.7).round(2)
    p["linked_pos_cogs_usd"] = (p.linked_pos_cash_usd * 0.32 + p.comp_cost_usd).round(2)
    p["tracked_contribution_usd"] = p.actual_tracked_loss_usd + p.linked_pos_cash_usd - p.linked_pos_cogs_usd
    p["comps_redeemed"] = rng.poisson((p.comp_cost_usd / 40).clip(0, 500))
    p["points_earned"] = (coin_share * ct.points_earned.reindex(idx).values).round().astype("int64")
    p["points_redeemed"] = (coin_share * ct.points_redeemed.reindex(idx).values).round().astype("int64")
    p["winner_flag"] = p.actual_tracked_loss_usd < 0
    p["above_expected_loss_flag"] = (p.actual_tracked_loss_usd > 2 * p.theo_usd) & (p.actual_tracked_loss_usd > 500)
    for c in ["tracked_coin_in_usd", "tracked_payout_usd", "tracked_net_usd", "actual_tracked_loss_usd"]:
        p[c] = p[c].round(2)
    return p


def comp_ratios(g: pd.DataFrame) -> pd.DataFrame:
    g["total_tracked_spend_usd"] = g.actual_tracked_loss_usd + g.linked_pos_cash_usd
    g["tracked_contribution_usd"] = g.actual_tracked_loss_usd + g.linked_pos_cash_usd - g.linked_pos_cogs_usd
    g["comp_cost_per_actual_loss"] = safe_div(g.comp_cost_usd, g.actual_tracked_loss_usd)
    g["comp_cost_per_total_spend"] = safe_div(g.comp_cost_usd, g.total_tracked_spend_usd)
    g["comp_cost_per_coin_in"] = safe_div(g.comp_cost_usd, g.tracked_coin_in_usd)
    g["theo_per_comp_cost"] = safe_div(g.tracked_theo_usd, g.comp_cost_usd)
    status = lambda s: np.select([s > 0, s == 0], ["positive_denominator", "zero_denominator"], "negative_denominator")
    g["actual_loss_ratio_status"] = status(g.actual_tracked_loss_usd)
    g["total_spend_ratio_status"] = status(g.total_tracked_spend_usd)
    return g


def placeholder_comps_tier(ph) -> pd.DataFrame:
    ct = ph["mart_comps_tier_month"].copy()
    ct["opening_tier"] = ct.tier.map(TIER_MAP)
    ct["month_start"] = pd.to_datetime(ct.month + "-01")
    return ct.groupby(["opening_tier", "month_start"])[
        ["comp_cost_usd", "theo_usd", "points_earned", "points_redeemed"]].sum().reset_index()


def build_comps_tier_month(players, ph_ct) -> pd.DataFrame:
    g = players.groupby(["opening_tier", "month_start"]).agg(
        active_players=("player_id", "nunique"), tracked_coin_in_usd=("tracked_coin_in_usd", "sum"),
        tracked_payout_usd=("tracked_payout_usd", "sum"), actual_tracked_loss_usd=("actual_tracked_loss_usd", "sum"),
        tracked_theo_usd=("theo_usd", "sum"), linked_pos_cash_usd=("linked_pos_cash_usd", "sum"),
        linked_pos_cogs_usd=("linked_pos_cogs_usd", "sum"), comp_face_value_usd=("comp_face_value_usd", "sum"),
        comp_cost_usd=("comp_cost_usd", "sum"), points_earned=("points_earned", "sum"),
        points_redeemed=("points_redeemed", "sum")).reset_index()
    cohort = players.groupby("opening_tier").player_id.nunique()
    g["cohort_players"] = g.opening_tier.map(cohort)
    g = g.sort_values(["opening_tier", "month_start"])
    g["points_balance_change"] = g.points_earned - g.points_redeemed
    g["points_balance_end"] = g.groupby("opening_tier").points_balance_change.cumsum()
    g["points_balance_start"] = g.points_balance_end - g.points_balance_change
    g = comp_ratios(g)
    g["policy_change_candidate"] = (g.opening_tier == "Gold") & (g.month_start == "2025-04-01")
    g["comparison_status"] = "placeholder"
    return g


def build_comps_daily(ph, tier_month, daily) -> pd.DataFrame:
    cd = ph["mart_comps_daily"].copy()
    cd["gaming_date"] = pd.to_datetime(cd.gaming_date)
    cd["month_start"] = month_start(cd.gaming_date)
    m = tier_month.groupby("month_start").sum(numeric_only=True)
    carded = daily.groupby("gaming_date").carded_coin_in_usd.sum()
    cd["w_play"] = cd.gaming_date.map(carded)
    cd["w_play"] /= cd.groupby("month_start").w_play.transform("sum")
    cd["w_comp"] = cd.comp_cost_usd / cd.groupby("month_start").comp_cost_usd.transform("sum")
    out = cd[["gaming_date", "month_start"]].copy()
    for col, w in [("tracked_coin_in_usd", "w_play"), ("tracked_theo_usd", "w_play"),
                   ("linked_pos_cash_usd", "w_play"), ("comp_cost_usd", "w_comp"),
                   ("comp_face_value_usd", "w_comp")]:
        out[col] = cd[w] * cd.month_start.map(m[col])
    out["linked_pos_cogs_usd"] = out.linked_pos_cash_usd * 0.32 + out.comp_cost_usd
    loss = out.tracked_theo_usd * (1 + rng.normal(0, 0.18, len(out)))
    loss *= out.month_start.map(m.actual_tracked_loss_usd) / loss.groupby(out.month_start).transform("sum")
    out["actual_tracked_loss_usd"] = loss
    out["tracked_payout_usd"] = out.tracked_coin_in_usd - loss
    out["points_earned"] = (cd.w_play * cd.month_start.map(m.points_earned)).round().astype("int64")
    out["points_redeemed"] = (cd.w_comp * cd.month_start.map(m.points_redeemed)).round().astype("int64")
    out["points_balance_change"] = out.points_earned - out.points_redeemed
    out["points_balance_end"] = out.points_balance_change.cumsum()
    out["points_balance_start"] = out.points_balance_end - out.points_balance_change
    out = comp_ratios(out)
    out["active_players"] = (cd.month_start.map(tier_month.groupby("month_start").active_players.sum()) / 9).round().astype("int64")
    out["policy_change_candidate"] = out.gaming_date == "2025-04-01"
    out["change_method"] = "placeholder"
    out["change_status"] = np.where(out.policy_change_candidate, "candidate", "no_change")
    return out


def build_visits(players) -> pd.DataFrame:
    p = players.assign(winning=lambda d: np.where(d.winner_flag, d.observed_visits - d.incomplete_visits, 0))
    g = p.groupby(["month_start", "home_region", "age_band", "opening_tier"]).agg(
        observed_visits=("observed_visits", "sum"), incomplete_visits=("incomplete_visits", "sum"),
        unique_players=("player_id", "nunique"), winning_visits=("winning", "sum"),
        visit_assigned_coin_in_usd=("tracked_coin_in_usd", "sum"),
        visit_assigned_payout_usd=("tracked_payout_usd", "sum"),
        visit_assigned_player_net_usd=("tracked_net_usd", "sum"),
        visit_assigned_pos_cash_usd=("linked_pos_cash_usd", "sum"),
        visit_assigned_theo_usd=("theo_usd", "sum")).reset_index()
    g["complete_visits"] = g.observed_visits - g.incomplete_visits
    g["visits_with_gaming"] = g.observed_visits
    g["coin_in_per_visit"] = safe_div(g.visit_assigned_coin_in_usd, g.observed_visits)
    g["winner_share_complete_visits"] = safe_div(g.winning_visits, g.complete_visits)
    return g


def build_benchmark(ph, floor) -> pd.DataFrame:
    b = ph["mart_benchmark_month"].pivot(index="month", columns="series", values="value")
    f = floor.groupby("month_start").agg(property_coin_in_usd=("coin_in_usd", "sum"),
                                         property_house_win_usd=("house_win_usd", "sum"),
                                         property_active_machine_days=("active_machines", "sum")).reset_index()
    f["property_coin_in_per_machine_day"] = f.property_coin_in_usd / f.property_active_machine_days
    f["missouri_coin_in_usd"] = f.month_start.dt.strftime("%Y-%m").map(b["Missouri slot coin-in"])
    f["missouri_house_win_usd"] = f.missouri_coin_in_usd * 0.09
    f["las_vegas_visitor_volume"] = f.month_start.dt.strftime("%Y-%m").map(b["LVCVA visitors"]).astype("int64")
    for src, dst in [("property_coin_in_per_machine_day", "property_coin_in_index"),
                     ("missouri_coin_in_usd", "missouri_coin_in_index"),
                     ("las_vegas_visitor_volume", "las_vegas_visitors_index")]:
        f[dst] = f[src] / f[src].iloc[0] * 100
    f["missouri_status"] = "placeholder"
    f["visitation_status"] = "placeholder"
    for c in ["missouri_source_url", "visitation_source_url", "source_revision", "as_of_limitation"]:
        f[c] = None
    return f


def build_tickets(ph, daily) -> pd.DataFrame:
    t = ph["mart_tickets"].copy()
    t["gaming_date"] = pd.to_datetime(t.opened_gaming_date)
    n = len(t)
    hour = t["shift"].map(SHIFT_START) + rng.uniform(0, 8, n)
    opened_local = t.gaming_date + pd.to_timedelta(hour, unit="h")
    opened = to_utc(opened_local)
    out = pd.DataFrame({"operation_id": t.ticket_id, "machine_id": t.machine_id,
                        "event_type": t.ticket_type.map(EVENT_MAP), "gaming_date": t.gaming_date})
    loc = daily.set_index(["machine_id", "gaming_date"]).location_id
    out["location_id"] = pd.MultiIndex.from_frame(out[["machine_id", "gaming_date"]]).map(loc.to_dict().get)
    out["controllable_fault"] = out.event_type == "fault_repair"
    out["opened_at_utc"] = opened
    out["recorded_at_utc"] = opened + pd.to_timedelta(rng.uniform(1, 6, n), unit="m")
    out["work_started_at_utc"] = opened + pd.to_timedelta(t.response_minutes, unit="m")
    out["available_at_utc"] = out.work_started_at_utc + pd.to_timedelta(t.repair_minutes, unit="m")
    out["response_hours"] = t.response_minutes / 60
    out["repair_hours"] = t.repair_minutes / 60
    out["total_outage_hours"] = out.response_hours + out.repair_hours
    out["direct_cost_usd"] = np.where(out.controllable_fault, 60 + t.repair_minutes * 1.4, 25.0).round(2)
    out["before_available_hours"] = (7 * 23.4 + rng.normal(0, 2, n)).round(1)
    out["after_available_hours"] = (7 * 23.4 + rng.normal(0, 2, n)).round(1)
    out["before_theo_per_hour"] = t.theo_per_hour_before
    out["after_theo_per_hour"] = t.theo_per_hour_after
    out["before_theo_usd"] = out.before_theo_per_hour * out.before_available_hours
    out["after_theo_usd"] = out.after_theo_per_hour * out.after_available_hours
    out["theo_rate_change"] = safe_div(out.after_theo_per_hour, out.before_theo_per_hour) - 1
    out["before_days"] = 7
    out["after_days"] = 7
    out["comparison_status"] = "complete"
    return out


def build_downtime(ph, daily) -> pd.DataFrame:
    dh = ph["mart_downtime_hourly"].copy()
    pos = daily.sort_values("gaming_date").groupby("machine_id")[
        ["location_id", "zone_id", "bank_id", "config_id", "manufacturer"]].last()
    dates = pd.Series(pd.date_range("2025-01-01", "2025-06-30"))
    by_wd = {wd: dates[dates.dt.day_name() == wd].to_numpy() for wd in dates.dt.day_name().unique()}
    rows = []
    down = dh[dh.unavailable_hours > 0]
    for r in down.itertuples():
        k = int(math.ceil(r.unavailable_hours))
        chosen = rng.choice(by_wd[r.weekday], size=min(k, len(by_wd[r.weekday])), replace=False)
        share = r.unavailable_hours / len(chosen)
        for d in chosen:
            rows.append((r.machine_id, d, r.hour, share, r.lost_theo_usd / len(chosen),
                         r.lost_theo_low_usd / len(chosen), r.lost_theo_high_usd / len(chosen), False))
    hidden = dh.groupby(["machine_id"]).hidden_downtime_hours.sum().round().astype(int)
    for m, k in hidden[hidden > 0].items():
        for _ in range(k):
            rows.append((m, rng.choice(dates.to_numpy()), int(rng.integers(0, 24)), 0.0, 0.0, 0.0, 0.0, True))
    h = pd.DataFrame(rows, columns=["machine_id", "gaming_date", "local_hour", "down_h", "lost", "low", "high",
                                    "hidden_downtime_flag"])
    h["gaming_date"] = pd.to_datetime(h.gaming_date)
    local = h.gaming_date + pd.to_timedelta(np.where(h.local_hour < 6, h.local_hour + 24, h.local_hour), unit="h")
    h["hour_start_utc"] = to_utc(local)
    h["utc_offset"] = np.where(local >= DST_START_LOCAL, "-07:00", "-08:00")
    h = h.join(pos, on="machine_id")
    h["scheduled_seconds"] = 3600
    h["downtime_seconds"] = (h.down_h * 3600).round().astype("int64")
    h["available_seconds"] = 3600 - h.downtime_seconds
    h["occupied_seconds"] = 0
    split = rng.dirichlet([7, 2, 1], len(h))
    h["fault_downtime_seconds"] = (h.downtime_seconds * split[:, 0]).round().astype("int64")
    h["planned_downtime_seconds"] = (h.downtime_seconds * split[:, 1]).round().astype("int64")
    h["other_downtime_seconds"] = h.downtime_seconds - h.fault_downtime_seconds - h.planned_downtime_seconds
    h["coin_in_usd"] = 0.0
    h["payout_usd"] = 0.0
    h["theo_usd"] = np.nan
    h["neighbor_count"] = rng.integers(3, 9, len(h))
    h["neighbor_available_hours"] = h.neighbor_count * 1.0
    h["usual_rate_ratio"] = rng.normal(1, 0.15, len(h)).round(3)
    h["estimated_lost_theo_usd"] = h.lost
    h["lost_theo_low_usd"] = h.low
    h["lost_theo_high_usd"] = h.high
    h["estimated_lost_coin_in_usd"] = h.lost / 0.085
    h["estimate_method"] = "peer_same_zone_other_bank"
    h["estimate_status"] = np.where(h.hidden_downtime_flag, "hidden_candidate", "ok")
    h["available_tech_staff_hours"] = 2.0
    return h.drop(columns=["down_h", "lost", "low", "high"])


def build_forecast(ph) -> pd.DataFrame:
    fc = ph["mart_forecast"].copy()
    fc["forecast_date"] = pd.to_datetime(fc.gaming_date)
    fc["split"] = fc.split.replace({"july_forecast": "future"})
    train = fc.split == "train"
    out = pd.DataFrame({"forecast_date": fc.forecast_date, "split": fc.split,
                        "actual_coin_in_usd": fc.actual_usd.where(fc.split != "future"),
                        "model_prediction_usd": fc.model_usd.where(~train),
                        "baseline_prediction_usd": fc.baseline_usd.where(~train),
                        "model_method": "weekday_average"})
    fit = {"validation": ("2025-01-01", "2025-03-31", "2025-04-01"),
           "test": ("2025-01-01", "2025-04-30", "2025-05-01"),
           "future": ("2025-01-01", "2025-06-30", "2025-07-01")}
    for i, col in enumerate(["fit_start", "fit_end", "forecast_origin"]):
        out[col] = pd.to_datetime(out.split.map(lambda s: fit.get(s, (None,) * 3)[i]))
    out["prediction_frozen_at_utc"] = pd.to_datetime(out.split.map(
        {"validation": "2025-04-01 12:00", "test": "2025-05-01 12:00", "future": "2025-07-01 12:00"}))
    out["evaluation_eligible"] = out.split.isin(["validation", "test"])
    out["weekday_index"] = out.forecast_date.dt.day_of_week
    return out


def build_actions(scorecard) -> pd.DataFrame:
    naive = scorecard[scorecard.naive_bottom_10]
    move_targets = list(naive[naive.location_flag].sort_values("naive_rank").machine_id[:8])
    inspect_targets = list(scorecard[scorecard.hold_anomaly_flag].sort_values("machine_id").machine_id[:4])
    rows = [dict(action_type_id="A-TECH-SHIFT", target_id="swing", target_type="shift", quantity=1,
                 lead_days=7, action_downtime_hours=0.0, unit_cost_usd=11_520.0, recurring_cost_per_day_usd=0.0,
                 benefit=29_520.0, low=9_000.0, high=27_000.0,
                 effect_assumption="Faster swing-shift response recovers a third of swing fault downtime.",
                 evidence_refs="mart_downtime_hourly;mart_tickets;mart_forecast",
                 measurement_metric="Lost theo per scheduled machine-hour on swing shift",
                 control_definition="Day and grave shifts over the same July dates",
                 limitation="Response time may already be improving; one month is a short window.")]
    for m in move_targets:
        rows.append(dict(action_type_id="A-MOVE-MACHINE", target_id=m, target_type="machine", quantity=1,
                         lead_days=2, action_downtime_hours=3.0, unit_cost_usd=1_800.0, recurring_cost_per_day_usd=0.0,
                         benefit=3_800.0, low=500.0, high=3_250.0,
                         effect_assumption="Moved machine earns 60% of its new zone's theo per open hour.",
                         evidence_refs="mart_machine_scorecard;mart_zone_daily",
                         measurement_metric="Expected contribution per available hour, before vs. after the move",
                         control_definition="Location-flagged machines that stay in place",
                         limitation="New neighbours may lose some play to the moved machine."))
    for m in inspect_targets:
        rows.append(dict(action_type_id="A-INSPECT", target_id=m, target_type="machine", quantity=1,
                         lead_days=1, action_downtime_hours=2.0, unit_cost_usd=1_200.0, recurring_cost_per_day_usd=0.0,
                         benefit=np.nan, low=np.nan, high=np.nan,
                         effect_assumption="Information only: confirms or clears the hold gap.",
                         evidence_refs="mart_machine_scorecard",
                         measurement_metric="Inspection outcome; observed vs. expected hold after",
                         control_definition="Not applicable",
                         limitation="A clean inspection does not prove the gap was luck."))
    a = pd.DataFrame(rows)
    a.insert(0, "proposal_line_id", [f"PL-{i + 1:02d}" for i in range(len(a))])
    a["selected"] = True
    a["horizon_start"] = pd.Timestamp("2025-07-01")
    a["horizon_end"] = pd.Timestamp("2025-07-30")
    a["effective_operating_days"] = (30 - a.lead_days).clip(lower=0).astype(float)
    a["additional_comp_cost_usd"] = 0.0
    a["total_cost_usd"] = a.quantity * (a.unit_cost_usd + a.recurring_cost_per_day_usd * a.effective_operating_days) \
        + a.additional_comp_cost_usd
    a["benefit_before_action_cost_usd"] = a.benefit
    a["net_benefit_usd"] = a.benefit - a.total_cost_usd
    a["benefit_low_usd"] = a.low
    a["benefit_high_usd"] = a.high
    a["half_effect_net_benefit_usd"] = 0.5 * a.benefit - a.total_cost_usd
    a["benefit_status"] = np.where(a.benefit.isna(), "information_only", "assumption")
    return a.drop(columns=["benefit", "low", "high"])


# =========================================================================================
def build(placeholder_dir: Path, db_path: Path) -> None:
    ph = load_placeholder(placeholder_dir)
    if not ph:
        raise SystemExit(f"No mart_*.csv files in {placeholder_dir}")
    print("Reshaping placeholder marts to docs/mart_contracts.md ...")
    daily = build_machine_daily(ph, ph["mart_tickets"])
    scorecard = build_scorecard(daily, ph)
    ph_ct = placeholder_comps_tier(ph)
    players = build_players(ph, ph_ct)
    tier_month = build_comps_tier_month(players, ph_ct)
    comps_daily = build_comps_daily(ph, tier_month, daily)
    floor = build_floor_daily(daily, ph, comps_daily)
    tables = {
        "mart_machine_daily": daily,
        "mart_machine_month": build_machine_month(daily, ph),
        "mart_machine_scorecard": scorecard,
        "mart_floor_daily": floor,
        "mart_zone_daily": build_zone_daily(daily, ph),
        "mart_visits_month": build_visits(players),
        "mart_benchmark_month": build_benchmark(ph, floor),
        "mart_downtime_hourly": build_downtime(ph, daily),
        "mart_tickets": build_tickets(ph, daily),
        "mart_player_month": players,
        "mart_comps_tier_month": tier_month,
        "mart_comps_daily": comps_daily,
        "mart_forecast": build_forecast(ph),
        "mart_actions": build_actions(scorecard),
    }

    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        con.execute("CREATE SCHEMA marts")
        for name, df in tables.items():
            df = df.copy()
            for c in df.columns:  # date-only columns as DATE, not TIMESTAMP
                if pd.api.types.is_datetime64_any_dtype(df[c]) and not c.endswith("_utc"):
                    df[c] = df[c].dt.date
            con.register("df_view", df)
            con.execute(f"CREATE TABLE marts.{name} AS SELECT * FROM df_view")
            con.unregister("df_view")
            print(f"  marts.{name:<26} {len(df):>8,} rows  {len(df.columns):>3} cols")
        con.execute("CREATE TABLE marts._placeholder AS SELECT 'Numbers are fake; shapes follow "
                    "docs/mart_contracts.md' AS note, now() AS built_at")
    tmp.replace(db_path)
    print(f"Wrote {len(tables)} contract-shaped tables to {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--placeholder", type=Path, default=HERE / "marts_placeholder")
    parser.add_argument("--db", type=Path, default=HERE / "casino.duckdb")
    args = parser.parse_args()
    build(args.placeholder, args.db)
