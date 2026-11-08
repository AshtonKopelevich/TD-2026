# Dashboard Royale processing pipeline

Build analytical marts from the official Parquet sources for a separate Flask app.
Source data stays in `dashboard-royale-main/data/` and is read-only.

## Current implementation: stages 1-5

- Explicit discovery of all 31 Parquet tables; CSV.gz duplicates are excluded.
- DuckDB `raw` source views, with no duplicate source ingestion/copy.
- Source release, manifest row count/file size, declared key, and minimum column/type checks.
- Optional full SHA-256 verification, plus versioned JSON inventory/validation reports.
- Analytical defaults in `src/casino_pipeline/constants.py`; unavailable thresholds remain `None`.
- Builds `marts.mart_machine_daily`: active machine-days, coordinates, meters,
  cost components, game variance, and exposure ratios.
- Validates source coverage, required values, keys, intervals, duration bounds,
  prepared-view reconciliation, accounting and ratios before publication.
- Tests include DST, partial days, moves, zero play, negative earnings, duplicate
  joins, and failed-build/publication safety.
- Stage 3 adds machine-month, floor-day, zone-day and benchmark-month tables,
  with sum reconciliation, coverage-aware traffic, weather quality handling and
  explicit benchmark provenance.
- Stage 4 adds player-month, visit-segment-month, daily comps and opening-tier
  monthly comps, with independently aggregated facts, points balances and coverage
  diagnostics.
- Stage 5 adds operations tickets and hourly downtime: de-duplicated outages,
  other-bank peer estimates, staffing context and pseudo-outage error diagnostics.
  Three contracted marts are still planned.

## Setup and run

Requires Python 3.11+ and uv:

```powershell
uv sync
uv run python run_all.py
uv run pytest
```

Optional full-file checksum verification:

```powershell
uv run python run_all.py --verify-hashes
```

Paths are independent of your current directory. Override them with:

```powershell
uv run python run_all.py --dataset "D:/datasets/dashboard-royale-main" --output-dir "D:/casino-output"
```

The existing `.venv` may refer to an unavailable Python installation. To leave it
untouched, choose a separate environment before syncing:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-pipeline"
uv sync
```

Exploration scripts are preserved. Install their optional dependencies with
`uv sync --extra explore`. `main.py` remains a separate scratch script.
`pyproject.toml` and `uv.lock` define the pipeline environment; `requirements.txt`
is the legacy exploration dependency list.

Run source checks only (without replacing any published database) using
`uv run python run_all.py --sources-only`.

The default builds through stage 5. Use `--stage 4` for the guest/comp marts only,
`--stage 3` for descriptive marts only or
`--stage 2` for the machine-day mart. `--stage 1` is equivalent to sources-only.
Stage 4 requires a whole-month analysis window within one year; app filters can
still select arbitrary dates from daily marts.

## Outputs

`output/casino.duckdb` is self-contained: it contains physical mart tables with
no source-file views. The default release produces 55,092 machine-days, excluding
1,018 off-floor rows. Zero-denominator ratios are NULL; negative earnings remain.

| Table | Grain | Default release rows |
| --- | --- | ---: |
| `marts.mart_machine_daily` | Machine x gaming date | 55,092 |
| `marts.mart_machine_month` | Machine x month | 1,834 |
| `marts.mart_floor_daily` | Gaming date | 181 |
| `marts.mart_zone_daily` | Zone x gaming date | 1,267 |
| `marts.mart_benchmark_month` | Month | 6 |
| `marts.mart_player_month` | Tracked player x month | 148,893 |
| `marts.mart_visits_month` | First-visit month x region x age x opening tier | 180 |
| `marts.mart_comps_daily` | Gaming date | 181 |
| `marts.mart_comps_tier_month` | Opening-tier cohort x month | 18 |
| `marts.mart_tickets` | Operations ticket overlapping the analysis window | 1,226 |
| `marts.mart_downtime_hourly` | Installed machine x UTC hour | 1,321,908 |

Monthly statistical outputs are NULL with `statistical_status='not_implemented'`
until stage 6. Floor contribution subtracts technician labor once. Zone traffic
uses an explicitly inferred full-day sensor roster; missing rows reduce coverage,
and offline entries remain NULL. Weather is calendar-date context, not a forecast
input. Benchmark indices use January=100, with NULL for missing/zero January
baselines; partial property months do not receive a property index.

Guest marts cover tracked players only. Visits assign all linked play/receipts to
the visit's first gaming month, while comp/player marts use activity months.
Comp cost is inside linked POS COGS and is deducted once. Loss/spend comp ratios
are NULL for nonpositive denominators. Redeemable points start at zero each year;
lifetime tier points are never used as a redeemable balance. Protective and
comp-change flags remain NULL with explicit configuration statuses.

`diagnostics.player_outcomes` summarizes fixed-window winners and gross-loss
concentration after first aggregating by player. `diagnostics.guest_coverage`
records excluded ledger events/visit cohorts and carded receipts without a visit.

Downtime losses are gross retrospective estimates, not identified net floor
losses after player substitution. References use healthy days in the same
placement/configuration and four-hour band within +/-28 gaming dates. Inadequate
peer/reference coverage gives NULL estimates. Error bounds are empirical scenarios
from deterministic pseudo-outages, not confidence intervals. See
`diagnostics.downtime_model_validation`, `downtime_validation_cases`, and
`downtime_coverage`. Hidden downtime stays NULL until BUSY_PEER_THRESHOLD is set.

```python
import duckdb

with duckdb.connect("output/casino.duckdb", read_only=True) as con:
    print(con.execute("""
        SELECT machine_id,
               SUM(theo_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0)
                   AS theo_per_available_hour
        FROM marts.mart_machine_daily
        GROUP BY machine_id
        ORDER BY theo_per_available_hour
        LIMIT 10
    """).fetchall())
```

The writer closes the temporary database before replacing the published file.
Validation failures and publication locks preserve the previous database. Close
app connections before replacement, particularly on Windows.

`output/reports/latest.json` points to a completed run under
`output/reports/runs/<build-id>/`. Each run contains:

- `manifest.json`: source release, schemas, metadata row counts, declared hashes,
  parameters, versions, build ID, Git revision and built-mart schemas.
- `validation.json`: individual source/mart checks, failures and verification scope.

Default validation scans key columns for uniqueness/nulls; it does not print source
records or load complete tables into pandas. Metadata row counts/bytes are not
content checksums. Use `--verify-hashes` to verify actual file contents against
the manifest. Tables without a documented primary key are inventoried without an
invented key assertion. Machine-day inputs have explicit required column/type
contracts; later stages add requirements as their transformations are implemented.

Exit code is 0 on success, 1 on validation/setup failure. Missing/corrupt sources
may fail before run reports are created. Failed validation reports never imply
that a new database has been published. `latest.json` may describe a failed attempt
while the previous successful database remains. Its embedded
`metadata.build_manifest` identifies the actually published build.

## Planned layout

`sql/staging/` holds shared transformations; `sql/marts/` holds final table assembly.
`src/casino_pipeline/analysis/` and `model/` will provide analytical intermediates.
Implemented SQL: the eleven marts above plus context, player activity, receipts,
loyalty, guest, ticket and hourly staging. `analysis/players.py` produces player
diagnostics; `analysis/downtime.py` builds outage evidence. Other analytical modules
and SQL remain placeholders.
`config/action_proposals.csv` starts empty; no recommendations are fabricated.

See [mart contracts](docs/mart_contracts.md), [methodology](docs/methodology.md)
and [app handoff](docs/app_handoff.md). Generated output is ignored by Git.
