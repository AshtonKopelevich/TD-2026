"""Make six exploratory charts from DuckDB aggregates (no full-table DataFrames).

Run: uv run --with duckdb --with matplotlib python plot_data.py
Outputs: charts/overview.png plus six individual PNG charts.
"""

import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # Save charts without requiring a desktop GUI.
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter


ROOT = Path(__file__).resolve().parent
MONEY = FuncFormatter(lambda x, _: f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}")


def load_summaries(dataset):
    with duckdb.connect() as con:
        for name, folder in [("daily", "1_prepared_views/prepared_daily_view"),
                             ("property", "1_prepared_views/property_day"),
                             ("players", "1_prepared_views/player_period"),
                             ("calendar", "2_machine_decision/calendar_day")]:
            path = (dataset / "data" / f"{folder}.parquet").as_posix()
            con.read_parquet(path).create_view(name)
        return {
            "daily": con.execute("""
                SELECT gaming_date, CAST(coin_in_usd AS DOUBLE),
                       CAST(house_win_usd AS DOUBLE), CAST(theo_usd AS DOUBLE),
                       AVG(CAST(coin_in_usd AS DOUBLE)) OVER (
                           ORDER BY gaming_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
                FROM property ORDER BY gaming_date
            """).fetchall(),
            "downtime": con.execute("""
                SELECT d.gaming_date,
                       SUM(c.scheduled_seconds / 3600.0 - d.available_hours)
                FROM daily d JOIN calendar c USING (gaming_date)
                WHERE d.active GROUP BY d.gaming_date ORDER BY d.gaming_date
            """).fetchall(),
            "machines": con.execute("""
                SELECT machine_id,
                       CAST(SUM(theo_usd) AS DOUBLE) / NULLIF(SUM(available_hours), 0),
                       CAST(SUM(house_win_usd) AS DOUBLE) / NULLIF(SUM(available_hours), 0)
                FROM daily WHERE active GROUP BY machine_id
                HAVING SUM(available_hours) > 0 ORDER BY machine_id
            """).fetchall(),
            "zones": con.execute("""
                SELECT COALESCE(zone_name, 'Unknown'),
                       CAST(SUM(coin_in_usd) AS DOUBLE) / NULLIF(SUM(available_hours), 0)
                FROM daily WHERE active GROUP BY zone_name
                HAVING SUM(available_hours) > 0 ORDER BY 2 DESC
            """).fetchall(),
            # Aggregate across months per player BEFORE binning the distribution.
            # Only histogram bins leave DuckDB, not 148k player-month rows.
            "players": con.execute("""
                WITH totals AS (
                    SELECT player_id, SUM(tracked_net_usd)::DOUBLE AS net
                    FROM players GROUP BY player_id
                ), bins AS (
                    SELECT FLOOR(net / 500.0) * 500.0 AS bin_start,
                           COUNT(*) AS players FROM totals GROUP BY 1
                ) SELECT bin_start, players FROM bins ORDER BY bin_start
            """).fetchall(),
        }


def dates(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


def draw_demand(ax, data):
    rows = data["daily"]
    ax.plot([r[0] for r in rows], [r[1] / 1e6 for r in rows], alpha=.45, label="Daily")
    ax.plot([r[0] for r in rows], [r[4] / 1e6 for r in rows], label="Trailing 7-day mean")
    ax.set(title="1. Daily wagering demand", ylabel="Coin-in ($ millions)")
    dates(ax)
    ax.legend()


def draw_win(ax, data):
    rows = data["daily"]
    ax.plot([r[0] for r in rows], [r[2] / 1000 for r in rows], label="Actual house win", alpha=.75)
    ax.plot([r[0] for r in rows], [r[3] / 1000 for r in rows], label="Theo (modeled expectation)")
    ax.axhline(0, color="gray", linewidth=.7)
    ax.set(title="2. Actual versus expected house win", ylabel="House win ($ thousands)")
    dates(ax)
    ax.legend(fontsize=8)


def draw_downtime(ax, data):
    rows = data["downtime"]
    ax.plot([r[0] for r in rows], [r[1] for r in rows], color="#c66b36")
    ax.set(title="3. Unavailable hours across active machines", ylabel="Machine-hours per gaming day")
    dates(ax)


def draw_machines(ax, data):
    rows = data["machines"]
    x, y = [r[1] for r in rows], [r[2] for r in rows]
    ax.scatter(x, y, s=16, alpha=.55)
    low, high = min(x + y), max(x + y)
    ax.plot([low, high], [low, high], "--", color="gray", label="Actual = theo")
    ax.set(title="4. Machine earnings, adjusted for availability",
           xlabel="Theo per available hour", ylabel="Actual house win per available hour")
    ax.xaxis.set_major_formatter(MONEY)
    ax.yaxis.set_major_formatter(MONEY)
    ax.legend(fontsize=8)


def draw_zones(ax, data):
    rows = list(reversed(data["zones"]))
    ax.barh([r[0] for r in rows], [r[1] for r in rows], color="#49998b")
    ax.set(title="5. Wagering demand by zone", xlabel="Coin-in per available machine-hour")
    ax.xaxis.set_major_formatter(MONEY)


def draw_players(ax, data):
    rows = data["players"]
    total = sum(r[1] for r in rows)
    ax.bar([r[0] + 250 for r in rows], [r[1] / total for r in rows], width=500, color="#8869aa")
    ax.set_xscale("symlog", linthresh=1000)
    ax.set_xticks([-10000, -1000, 0, 1000, 10000])
    ax.xaxis.set_major_formatter(MONEY)
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.axvline(0, color="gray", linewidth=.8)
    ax.set(title="6. Tracked player net: full six-month window",
           xlabel="Payout minus wagers ($500 bins; signed log axis)", ylabel="Share of tracked players")


PLOTS = [("daily_demand", draw_demand), ("actual_vs_expected", draw_win),
         ("downtime", draw_downtime), ("machine_performance", draw_machines),
         ("zone_demand", draw_zones), ("tracked_player_net", draw_players)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dashboard-royale-main")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "charts")
    args = parser.parse_args()
    summaries = load_summaries(args.dataset.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.titlesize": 11, "font.size": 9})
    fig, axes = plt.subplots(3, 2, figsize=(17, 14), layout="constrained")
    for ax, (name, draw) in zip(axes.flat, PLOTS):
        draw(ax, summaries)
        ax.grid(axis="y", alpha=.15)
        individual, single_ax = plt.subplots(figsize=(10, 6), layout="constrained")
        draw(single_ax, summaries)
        single_ax.grid(axis="y", alpha=.15)
        individual.savefig(args.output_dir / f"{name}.png", dpi=160)
        plt.close(individual)
    fig.suptitle("The Gilded Ace | Jan-Jun 2025 | Exploratory overview (synthetic casino data)", fontsize=16)
    fig.supxlabel("All play except chart 6 (tracked only). Active machine-days only in charts 3-5.\n"
                  "Theo is a model expectation; zone differences and earnings gaps alone do not establish causes.", fontsize=10)
    fig.savefig(args.output_dir / "overview.png", dpi=160)
    plt.close(fig)
    print(f"Saved overview and {len(PLOTS)} individual charts to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
