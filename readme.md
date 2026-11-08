# Dashboard Royale: The Gilded Ace

This project combines a Python/DuckDB processing pipeline with The Gilded Ace,
a Flask dashboard that presents the analysis in seven chapters. The pipeline
builds fourteen analytical marts from the official Parquet sources; the dashboard
queries them for machine performance, demand, downtime, guests, forecasts and
action proposals. Source data stays in `dashboard-royale-main/data/` and is
read-only. The shared interface is defined in [mart contracts](docs/mart_contracts.md).

## Quick start

Requires Python 3.11+ and uv. From the repository root:

```powershell
uv sync --extra dashboard
uv run python run_all.py
uv run python -m dashboard.app
```

Open http://127.0.0.1:5000. If `output/casino.duckdb` already exists, skip the
build command to use the current marts. Stop the app before rebuilding and
restart it afterward, particularly on Windows. For processing only, use
`uv sync` without the dashboard extra.

## Current implementation: stages 1-8

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
- Stage 6 adds a full-window machine scorecard, CLT/BH tests, paired block-bootstrap
  sensitivity intervals, peer/location comparisons and overlapping evidence flags.
  Monthly CLT outputs are enriched separately.
- Stage 7 adds frozen backtest/July forecasts and explicit proposal costing. All
  fourteen contracted marts are generated.
- Stage 8 inspects the standalone artifact, generates its dictionary and handoff
  reports, compares a previous build, and optionally exports marts or checks Flask routes.

## Processing setup and options

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
`pyproject.toml` and `uv.lock` define the shared environment, including optional
dashboard dependencies. `requirements.txt` provides the legacy pip setup used
by exploration scripts and the dashboard.

Run source checks only (without replacing any published database) using
`uv run python run_all.py --sources-only`.

The default builds through stage 8. Use `--stage 7` to skip final handoff packaging,
`--stage 6` to stop before forecasting/actions,
`--stage 5` to stop before scorecard statistics,
`--stage 4` for the guest/comp marts only,
`--stage 3` for descriptive marts only or
`--stage 2` for the machine-day mart. `--stage 1` is equivalent to sources-only.
Stage 4 requires a whole-month analysis window within one year; app filters can
still select arbitrary dates from daily marts.

## Running the dashboard

The app reads the fourteen contract tables from the `marts` schema. It chooses
its database in this order:

1. The `CASINO_DB` environment variable.
2. `output/casino.duckdb`, produced by the pipeline.
3. `casino.duckdb` in the repository root, the optional placeholder database.

To use an alternate pipeline output, set the database path before starting Flask:

```powershell
$env:CASINO_DB = "D:/casino-output/casino.duckdb"
uv run python -m dashboard.app
```

The app resolves the database at startup, so restart it after changing paths or
switching to real marts. The placeholder banner normally appears only when the
database contains `marts._placeholder`. `CASINO_PLACEHOLDER` can override detection.

For presentation work before building real marts, generate placeholder data:

```powershell
uv run python build_duckdb.py
$env:CASINO_DB = (Join-Path $PWD "casino.duckdb")
uv run python -m dashboard.app
```

Remove that override with `Remove-Item Env:CASINO_DB` to return to the default
lookup. Placeholder generation is separate from the validated pipeline.

The dashboard also reads the source action catalogue for names and constraints.
`CASINO_SOURCE` defaults to `dashboard-royale-main/data`; set it to the source
data directory when sources live elsewhere. `CASINO_SCHEMA` defaults to `marts`.
The database itself is self-contained; these source reads are dashboard context.

The opening page links to `/verdict`, `/machines`, `/demand`, `/downtime`,
`/guests`, `/forecast` and `/plan`. Machine details use `/machines/<machine_id>`.
Shared filters query the marts; full-window scorecard classifications retain
their original analysis window.

### Dashboard contract conventions

- Scorecard classification codes map to display labels in `dashboard/contract.py`.
  The adjusted bottom ten uses `adjusted_rank <= 10`; the manager's comparison
  uses `naive_bottom_10`.
- Action benefit bounds are **before proposal costs**; `net_benefit_usd` is after
  costs. The current dashboard range display needs this distinction; see
  [consumer interpretation notes](docs/app_handoff.md#interpretation-differences-for-the-dashboard-owner).
- `mart_actions.evidence_refs` holds semicolon-separated mart references that
  link to chapters. Action names come from the source catalogue, with short
  labels in `contract.ACTION_SHORT`.
- `policy_change_candidate` marks candidate dates when configured. NULL flags,
  including protective and hidden-downtime flags, mean unavailable.
- `mart_downtime_hourly.local_hour` is local clock time. Gaming days run from
  06:00 to 06:00; shifts are day 06-14, swing 14-22 and grave 22-06.
- Concentration curves and winner share aggregate each player across the
  selected months before computing the distribution.

Use [app handoff](docs/app_handoff.md) for interpretation limitations and pending
presentation adjustments alongside the contracts and methodology.

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
| `marts.mart_machine_scorecard` | Machine, fixed analysis window | 310 |
| `marts.mart_forecast` | Historical/forecast date | 211 |
| `marts.mart_actions` | Configured proposal x target | 0 with empty default config |

Full-window CLT tests require 60 active and 30 positive-wager dates; monthly tests
require 21 and 14. BH correction is separate for the full-window family and each
month. Bootstrap intervals require eight complete seven-day blocks, so monthly
intervals remain NULL with explicit insufficient-block status. Full-window intervals
use 10,000 seeded resamples within placement episodes; they are sensitivity checks,
not a second set of hypothesis-test p-values. Scorecard rankings/classifications
are fixed to the build's analysis dates, not recomputed by app date filters.

Floor contribution subtracts technician labor once. Zone traffic
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

Forecasting selects weekday means versus calendar regression using April, freezes
May-Jun predictions from Jan-Apr fits, scores them against a constant-mean baseline,
then refits the selected method on Jan-Jun for July 1-30. Diagnostics retain
candidate errors, coefficients, feature cutoffs, frozen predictions and weekday MAE.
Only calendar/advance-announced events are inputs; no weather or later tourism data.
July holiday flags are explicitly configured for this horizon (July 4).

`config/action_proposals.csv` is empty by default: no funded recommendations or
causal benefits are invented. `diagnostics.action_portfolio` reports the full
$100,000 unallocated; `metadata.action_catalog` retains all 13 catalogue options.
See [proposal configuration](docs/action_proposals.md) for scenario fields and rules.
Use another file with `uv run python run_all.py --action-proposals path/to/actions.csv`.

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

## Repository layout

`sql/staging/` holds shared transformations; `sql/marts/` holds final table assembly.
`src/casino_pipeline/analysis/` and `model/` provide analytical intermediates.
Implemented SQL: the fourteen marts above plus context, player activity, receipts,
loyalty, guest, ticket and hourly staging. `analysis/players.py` produces player
diagnostics; `analysis/downtime.py` builds outage evidence; `analysis/machines.py`
builds statistical evidence. `model/forecast.py` controls chronological fitting and
freezing; `actions.py` validates and prices explicit proposals. `handoff.py` inspects
published artifacts and `export.py` streams optional CSV/Parquet exports.
`config/action_proposals.csv` starts empty; no recommendations are fabricated.

See [mart contracts](docs/mart_contracts.md), [methodology](docs/methodology.md)
and [app handoff](docs/app_handoff.md). Generated output is ignored by Git.

| Dashboard path | Purpose |
| --- | --- |
| `dashboard/app.py` | Flask routes and chapter rendering |
| `dashboard/data.py` | Database lookup, read-only queries, shared filters and schema-qualified names |
| `dashboard/contract.py` | Display labels for contract codes and chapter-to-mart mappings |
| `dashboard/pages.py` | Opening page, chapter builders and machine detail |
| `dashboard/charts.py` | Plotly theme and table helper |
| `dashboard/templates/`, `dashboard/static/` | Templates, styling and assets |
| `build_duckdb.py` | Optional placeholder database generator |

When changing a contract code or column, review `dashboard/contract.py` and its
uses in `dashboard/pages.py` as well as the pipeline contract.

## Final handoff and exports

```powershell
uv sync --extra dashboard
uv run python run_all.py --verify-hashes --export parquet --check-dashboard
```

The dashboard check uses Flask's in-process test client, not a running server.
It checks the actual consumer's routes and filtered queries; it does not certify
visual presentation or the wording of findings. Dashboard fixes remain with its owner.

After fixing a failed route, retry only previous failures without rebuilding:

```powershell
uv run python run_all.py --recheck-dashboard-failures
```

Without rebuilding the analyses:

```powershell
uv run python run_all.py --handoff-only
uv run python run_all.py --handoff-only --export both
uv run python run_all.py --handoff-only --check-dashboard
```

`--export-only` is an alias for `--handoff-only`; combine it with `--export`.
Exports are optional: keep DuckDB as the app's main data source. Parquet preserves
SQL types and uses ZSTD compression; CSV loses types and can be much larger for
hourly data. Files are ordered by key, checked for row counts/schema, and checksummed.

- `output/reports/handoff.md`: stable summary for the most recently inspected build.
- `output/reports/latest_handoff.json`: pointer to the detailed JSON and dictionary.
- `output/reports/runs/<build-id>/data_dictionary.md`: generated column/type/key listing.
- `output/exports/<build-id>/<format>/`: optional mart files.
- `output/exports/latest.json`: pointer to the verified export manifest.

The source build report and handoff report are distinct: an artifact can pass data
validation while a consumer route still needs work. The JSON reports show both.
Rebuild comparison uses order-independent diagnostic row hashes, excludes the
deliberately changing forecast-freeze timestamp, and normalizes floating precision.
It is a practical comparison with a prior artifact, not a second full rebuild or
cryptographic proof of equal values. Source and output SHA-256 hashes are separate.

See [handoff checklist](docs/final_handoff.md) for delivery and refresh instructions.
