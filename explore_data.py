"""Inventory Parquet schemas and map the challenge questions to available data.

Run: python explore_data.py
Only Parquet metadata is inspected; no data rows are loaded or printed.
"""

import argparse
from collections import Counter
from pathlib import Path
import re

import duckdb


ROOT = Path(__file__).resolve().parent
QUESTIONS = [
    ("Q1", ["prepared_daily_view"],
     ["machine_day", "game_math", "placements", "machines", "floor_locations", "floor_walkways", "calendar_day", "cost_rules"],
     "Compare theo, house win and contribution per available hour; account for active days, location, RTP and volatility.",
     r"machine_id|gaming_date|active|available|occupied|occupancy|coin_in|house_win|theo|luck|rtp|volatility|zone|location|config|effective|cost|contribution"),
    ("Q2", ["property_day", "zone_traffic_hourly"],
     ["events", "calendar_day", "prepared_daily_view", "placements", "city_visitation_monthly", "weather_daily", "visitor_profile_summary", "visitor_profile_segments", "benchmark_public", "benchmark_property_monthly", "benchmark_state_monthly", "visitor_profile_monthly"],
     "Compare daily/monthly demand and zone patterns with events, weather and city trends. Associations do not establish causes; public benchmarks describe other populations.",
     r"date|month|zone|entries|coverage|counter_status|coin_in|occupied|event|holiday|visitor|occupancy|precip|temp|announced|published|release"),
    ("Q3", ["prepared_daily_view", "operations", "calendar_day"],
     ["machine_day", "machine_hour", "shift_roster", "machines"],
     "Estimate lost play from a comparable-machine/time baseline and unavailable hours. Lost play is an estimate, not an observed column; use scheduled_seconds for DST.",
     r"machine_id|gaming_date|hour|available|downtime|scheduled|start|end|opened|closed|fault|repair|ticket|role|shift|manufacturer|coin_in|active"),
    ("Q4", ["player_period"], ["sessions", "trips", "players", "machine_day"],
     "Summarize tracked wagers, payouts, player net and concentration by player/group. Player net = payout minus wagers; these tables cover carded play only.",
     r"player_id|period_month|coin_in|payout|net|theo|luck|region|age_band|tier|visit|carded|observation_complete"),
    ("Q5", ["player_period", "property_day"], ["loyalty_ledger", "fnb_transactions", "players"],
     "Track points, redemptions, economic comp cost and cost/theo over time and by tier. Comp cost is already included in linked POS COGS; do not subtract twice.",
     r"player_id|date|month|points|comp|cost|cogs|tier|redeem|event|theo|contribution|policy|rate"),
    ("Q6", ["action_catalog", "cost_rules"],
     ["prepared_daily_view", "property_day", "operations", "placements", "game_math", "player_period", "loyalty_ledger", "fnb_transactions", "zone_traffic_hourly", "shift_roster"],
     "Recommend up to 3 action types within $100,000 for July 1-30, 2025. Price quantities, lead times, recurring costs and incompatibilities; give expected effects, uncertainty and a measurement/control plan. Keeping the budget is valid; catalogue prices do not imply benefits.",
     r"action|cost|quantity|lead|downtime|incompat|target|unit|recurring|contribution|theo|available"),
]


def read_dictionary(path):
    """Extract supplied descriptions and keys; schemas come from actual files."""
    tables = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^### (\w+)\s*$", line)
        if heading:
            current = tables.setdefault(heading[1], {"notes": [], "columns": {}})
        elif line.startswith("## "):
            current = None
        elif current is not None:
            column = re.match(r"^\| `([^`]+)` \| ([^|]+) \| (.*) \|\s*$", line)
            if column:
                current["columns"][column[1]] = column[3].strip()
            elif line.strip() and not line.startswith("|"):
                current["notes"].append(line)
    return tables


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_report(dataset):
    data = dataset / "data"
    paths = sorted(data.rglob("*.parquet"))
    if not paths:
        raise ValueError(f"No Parquet files found in {data}")
    dictionary = read_dictionary(dataset / "reference" / "DATA_DICTIONARY.md")
    guide = (dataset / "GUIDE.md").read_text(encoding="utf-8")
    challenge = guide.split("**Your job.**", 1)[1].split("These six questions", 1)[0]
    questions = re.findall(r"^\d+\. (.+)$", challenge, re.MULTILINE)
    if len(questions) != 6:
        raise ValueError("Expected six challenge questions in GUIDE.md")

    inventory = {}
    with duckdb.connect() as con:
        for path in paths:
            name = path.stem
            if name in inventory:
                raise ValueError(f"Duplicate table name: {name}")
            # DESCRIBE binds the Parquet schema; metadata supplies row counts.
            schema = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            rows = con.execute(
                "SELECT num_rows FROM parquet_file_metadata(?)", [str(path)]
            ).fetchone()[0]
            inventory[name] = {"path": path.relative_to(dataset).as_posix(),
                               "rows": rows, "schema": schema}

    types = Counter(row[1] for table in inventory.values() for row in table["schema"])
    lines = ["# Dataset inventory and question map", "",
             "Generated with DuckDB from Parquet schemas and file metadata; no data rows scanned or printed. CSV.gz files duplicate the Parquet tables and are excluded.", "",
             f"**{len(inventory)} tables; {sum(t['rows'] for t in inventory.values()):,} stored rows across tables.** These are different grains and overlapping views, not distinct observations.", "",
             "## Available SQL types", "", "| SQL type | Column count |", "| --- | ---: |"]
    lines.extend(f"| {cell(t)} | {n} |" for t, n in sorted(types.items()))
    lines.extend(["", "DECIMAL preserves fixed precision (including money); BIGINT/INTEGER store counts or cents; DOUBLE stores approximate measures; VARCHAR stores labels/IDs; DATE/TIMESTAMP store time; BOOLEAN stores flags. A timestamp's `_utc`/`_local` suffix conveys its timezone convention.", "",
                  "## Required questions and relevant data", "",
                  "Question wording comes from GUIDE.md. Starter/drill-down roles follow its mapping; additional tables and column selections below are suggested analysis aids, not statistical correlations."])
    for (qid, starters, deeper, approach), question in zip(
        [(q[0], q[1], q[2], q[3]) for q in QUESTIONS], questions
    ):
        pattern = next(q[4] for q in QUESTIONS if q[0] == qid)
        lines.extend(["", f"### {qid}: {question}", "",
                      "Start with: " + ", ".join(f"`{t}`" for t in starters) + ".", "",
                      "Drill down/context: " + ", ".join(f"`{t}`" for t in deeper) + ".", "", approach, "",
                      "| Table | Relevant columns (actual SQL types) |", "| --- | --- |"])
        for name in starters + deeper:
            if name not in inventory:
                raise ValueError(f"Question mapping references missing table: {name}")
            selected = [f"`{r[0]}` ({r[1]})" for r in inventory[name]["schema"] if re.search(pattern, r[0])]
            lines.append(f"| {name} | {cell(', '.join(selected) or 'See full schema below for contextual fields.')} |")
    lines.extend(["", "## Additional requirements and analysis cautions", "",
                  "- Include one useful ML/time-series method with a simple baseline and time-based holdout. Suggested route: forecast property_day coin-in using calendar_day weekday; train January-April, evaluate May-June with MAE. Avoid future information.",
                  "- Dashboard: allow period changes and bank/guest-group drill-down; show model validation and trace each recommendation to evidence.",
                  "- Deliver a public interactive dashboard, <=2-minute video, <=400-word write-up, code, Claims & Evidence appendix and AI-use disclosure (GUIDE.md sections 7-8).",
                  "- Aggregate separate fact tables to a shared grain before joining; joining sessions and receipts row-by-row multiplies money.",
                  "- Placements require interval joins: effective_from_utc <= timestamp < effective_to_utc; use prepared_daily_view for already-resolved machine-day location.",
                  "- Exclude inactive machine-days from performance comparisons; missing traffic counts are not zero and entries are not unique people.",
                  "- Compute ratios from sums. Preserve cents versus dollars, house versus player net signs, and carded versus all-play coverage.",
                  "- Source dataset is fictional/synthetic except separate real_sources files; January-June 2025; gaming days start 06:00 America/Los_Angeles. Release is a draft.", "",
                  "## Full table and column inventory", ""])
    for name, table in inventory.items():
        docs = dictionary.get(name, {"notes": [], "columns": {}})
        lines.extend([f"### {name}", "", f"File: `{table['path']}`; metadata rows: **{table['rows']:,}**.", ""])
        lines.extend(docs["notes"] + [""])
        lines.extend(["| Column | Actual DuckDB type | Meaning from dictionary |", "| --- | --- | --- |"])
        for row in table["schema"]:
            lines.append(f"| `{row[0]}` | {cell(row[1])} | {cell(docs['columns'].get(row[0], 'Not documented'))} |")
        lines.append("")
    return "\n".join(lines), inventory, types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dashboard-royale-main")
    parser.add_argument("--output", type=Path, default=ROOT / "data_inventory.md")
    parser.add_argument("--full", action="store_true", help="Also print the full report to the terminal")
    args = parser.parse_args()
    report, inventory, types = build_report(args.dataset.resolve())
    args.output.write_text(report, encoding="utf-8")
    if args.full:
        print(report)
    else:
        print(f"{'Table':38} {'Rows':>12} {'Columns':>8}")
        for name, table in inventory.items():
            print(f"{name:38} {table['rows']:12,} {len(table['schema']):8}")
        print("\nSQL types: " + ", ".join(sorted(types)))
        print("\nQuestion starters:")
        for qid, starters, *_ in QUESTIONS:
            print(f"  {qid}: {', '.join(starters)}")
        print(f"\nFull schemas, meanings and question mappings: {args.output.resolve()}")


if __name__ == "__main__":
    main()
