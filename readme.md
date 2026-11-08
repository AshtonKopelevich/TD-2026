# Dashboard Royale processing pipeline

Build analytical marts from the official Parquet sources for a separate Flask app.
Source data stays in `dashboard-royale-main/data/` and is read-only.

## Current implementation: stages 1-2

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
  joins, and failed-build/publication safety. The other 13 marts are not built yet.

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

## Outputs

`output/casino.duckdb` is self-contained: it contains physical mart tables with
no source-file views. The default release produces 55,092 machine-days, excluding
1,018 off-floor rows. Zero-denominator ratios are NULL; negative earnings remain.

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
SQL other than `sql/marts/machine_daily.sql`, and analytical Python modules,
remain explicitly marked placeholders until their stages are implemented.
`config/action_proposals.csv` starts empty; no recommendations are fabricated.

See [mart contracts](docs/mart_contracts.md), [methodology](docs/methodology.md)
and [app handoff](docs/app_handoff.md). Generated output is ignored by Git.
