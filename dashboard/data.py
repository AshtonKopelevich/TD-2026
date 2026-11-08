"""DuckDB access and the shared filter bar.

Every query reads the `marts` schema defined in docs/mart_contracts.md. The dashboard
looks for a database in this order:

  1. the CASINO_DB environment variable
  2. output/casino.duckdb   (where the real pipeline writes, per the contract)
  3. casino.duckdb          (the placeholder build from build_duckdb.py)

so once the real pipeline has run, the dashboard switches to real data on its own.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = Path(os.environ.get("CASINO_SOURCE", ROOT / "dashboard-royale-main" / "data"))
SCHEMA = os.environ.get("CASINO_SCHEMA", "marts")


def _resolve_db() -> Path:
    if os.environ.get("CASINO_DB"):
        return Path(os.environ["CASINO_DB"])
    real = ROOT / "output" / "casino.duckdb"
    return real if real.exists() else ROOT / "casino.duckdb"


DB_PATH = _resolve_db()
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 6, 30)


def T(name: str) -> str:
    """Fully qualified mart name, e.g. T('mart_floor_daily') -> marts.mart_floor_daily."""
    return f"{SCHEMA}.{name}"


def query(sql: str, params: list | tuple = ()) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


def scalar(sql: str, params: list | tuple = ()):
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        row = con.execute(sql, list(params)).fetchone()
    return row[0] if row else None


def _db_stamp() -> float:
    return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0


@lru_cache(maxsize=4)
def _is_placeholder(_stamp: float) -> bool:
    return bool(scalar("SELECT COUNT(*) FROM information_schema.tables "
                       "WHERE table_schema = ? AND table_name = '_placeholder'", [SCHEMA]))


def is_placeholder() -> bool:
    override = os.environ.get("CASINO_PLACEHOLDER")
    return override != "0" if override is not None else _is_placeholder(_db_stamp())


@lru_cache(maxsize=4)
def _options(_stamp: float) -> dict:
    zones = query(f"""SELECT zone_id, any_value(zone_name) zone_name FROM {T('mart_machine_daily')}
                      GROUP BY zone_id ORDER BY zone_name""")
    banks = query(f"""SELECT bank_id, arg_max(zone_id, gaming_date) zone_id FROM {T('mart_machine_daily')}
                      GROUP BY bank_id ORDER BY bank_id""")
    guests = query(f"SELECT DISTINCT opening_tier, age_band, home_region FROM {T('mart_player_month')}")
    tier_order = ["Base", "Bronze", "Silver", "Gold", "Platinum"]

    def ordered(values, order=(), last=("Unknown",)):
        vals = [v for v in values if pd.notna(v)]
        return sorted(vals, key=lambda v: (v in last, order.index(v) if v in order else len(order), v))

    return {
        "zones": zones.to_dict("records"),
        "zone_names": dict(zip(zones.zone_id, zones.zone_name)),
        "banks": banks.to_dict("records"),
        "tiers": ordered(guests.opening_tier.unique(), tier_order),
        "age_bands": ordered(guests.age_band.unique()),
        "home_regions": ordered(guests.home_region.unique()),
    }


def filter_options() -> dict:
    """Dropdown values, read from the data so new zones or tiers appear automatically."""
    return _options(_db_stamp())


def zone_name(zone_id: str) -> str:
    return filter_options()["zone_names"].get(zone_id, zone_id)


def _parse_date(value: str | None, default: date) -> date:
    try:
        d = date.fromisoformat(value) if value else default
    except ValueError:
        return default
    return min(max(d, PERIOD_START), PERIOD_END)


@dataclass(frozen=True)
class Filters:
    start: date = PERIOD_START
    end: date = PERIOD_END
    zone: str = ""          # zone_id
    bank: str = ""          # bank_id
    tier: str = ""          # opening_tier
    age_band: str = ""
    home_region: str = ""
    diag: str = ""          # machine explorer: highlight one primary_classification

    @classmethod
    def from_args(cls, args) -> "Filters":
        start = _parse_date(args.get("start"), PERIOD_START)
        end = _parse_date(args.get("end"), PERIOD_END)
        if start > end:
            start, end = end, start
        zone, bank = args.get("zone", ""), args.get("bank", "")
        if bank:
            bank_zone = {b["bank_id"]: b["zone_id"] for b in filter_options()["banks"]}.get(bank)
            if bank_zone is None or (zone and bank_zone != zone):
                bank = ""  # unknown bank, or a bank from another zone
            else:
                zone = bank_zone
        return cls(start, end, zone, bank, args.get("tier", ""), args.get("age_band", ""),
                   args.get("home_region", ""), args.get("diag", ""))

    # ---- SQL fragments -------------------------------------------------------------
    def where(self, date_col: str | None = "gaming_date", location: bool = True,
              alias: str = "") -> tuple[str, list]:
        p = f"{alias}." if alias else ""
        clauses, params = ["TRUE"], []
        if date_col:
            clauses.append(f"{p}{date_col} BETWEEN ? AND ?")
            params += [self.start, self.end]
        if location and self.zone:
            clauses.append(f"{p}zone_id = ?")
            params.append(self.zone)
        if location and self.bank:
            clauses.append(f"{p}bank_id = ?")
            params.append(self.bank)
        return " AND ".join(clauses), params

    def where_month(self, col: str = "month_start", guests: bool = False,
                    skip: tuple = ()) -> tuple[str, list]:
        clauses = [f"{col} BETWEEN date_trunc('month', ?::DATE) AND date_trunc('month', ?::DATE)"]
        params: list = [self.start, self.end]
        if guests:
            for field, col_name in (("tier", "opening_tier"), ("age_band", "age_band"),
                                    ("home_region", "home_region")):
                if getattr(self, field) and field not in skip:
                    clauses.append(f"{col_name} = ?")
                    params.append(getattr(self, field))
        return " AND ".join(clauses), params

    # ---- display -------------------------------------------------------------------
    @property
    def is_full_period(self) -> bool:
        return self.start == PERIOD_START and self.end == PERIOD_END

    @property
    def location_label(self) -> str:
        if self.bank:
            return f"Bank {self.bank} in {zone_name(self.zone)}"
        return zone_name(self.zone) if self.zone else "Whole floor"

    @property
    def guest_label(self) -> str:
        parts = []
        if self.tier:
            parts.append(f"{self.tier} tier")
        if self.age_band:
            parts.append(f"age {self.age_band}")
        if self.home_region:
            parts.append(self.home_region)
        return ", ".join(parts) if parts else "All card holders"

    @property
    def period_label(self) -> str:
        if self.is_full_period:
            return "January to June 2025"
        if self.start.month == self.end.month and self.start.day == 1 and \
                (self.end + pd.Timedelta(days=1)).day == 1:
            return f"{self.start:%B} 2025"
        return f"{self.start:%b} {self.start.day} to {self.end:%b} {self.end.day}, {self.end.year}"

    def qs(self, **overrides) -> str:
        f = replace(self, **overrides) if overrides else self
        params = {
            "start": f.start.isoformat() if f.start != PERIOD_START else "",
            "end": f.end.isoformat() if f.end != PERIOD_END else "",
            "zone": f.zone, "bank": f.bank, "tier": f.tier, "age_band": f.age_band,
            "home_region": f.home_region, "diag": f.diag,
        }
        params = {k: v for k, v in params.items() if v}
        return ("?" + urlencode(params)) if params else ""


@lru_cache(maxsize=1)
def action_catalog() -> pd.DataFrame:
    """The source action_catalog (names, limits, incompatibilities). Not a mart: it is
    read-only source data, so it's read straight from the Parquet file when present."""
    path = SOURCE_DIR / "2_machine_decision" / "action_catalog.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["action_type_id", "name", "quantity_limit", "incompatibility_group"])
    with duckdb.connect() as con:
        return con.execute("SELECT * FROM read_parquet(?)", [path.as_posix()]).df()
