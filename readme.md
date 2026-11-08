# Dashboard Royale processing pipeline

Build analytical marts from the official Parquet sources for a separate Flask app.
Source data stays in `dashboard-royale-main/data/` and is read-only.

## Current implementation: stage 1

- Explicit discovery of all 31 Parquet tables; CSV.gz duplicates are excluded.
- In-memory DuckDB schemas and `raw` source views, with no data ingestion/copy.
- Source release, manifest row count/file size, declared key, and minimum column/type checks.
- Optional full SHA-256 verification, plus versioned JSON inventory/validation reports.
- Analytical defaults in `src/casino_pipeline/constants.py`; unavailable thresholds remain `None`.
- Tests use small synthetic Parquet fixtures. No mart transformations, statistics,
  forecasts, or `casino.duckdb` are published in this stage.

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

## Stage-one outputs

`output/reports/latest.json` points to a completed run under
`output/reports/runs/<build-id>/`. Each run contains:

- `manifest.json`: source release, schemas, metadata row counts, declared hashes,
  parameters, versions, build ID and available Git revision.
- `validation.json`: individual checks, failures and verification scope.

Default validation scans key columns for uniqueness/nulls; it does not print source
records or load complete tables into pandas. Metadata row counts/bytes are not
content checksums. Use `--verify-hashes` to verify actual file contents against
the manifest. Tables without a documented primary key are inventoried without an
invented key assertion. Minimum schema checks are currently strongest for machine
inputs; later stages add requirements as their transformations are implemented.

Exit code is 0 on success, 1 on validation/setup failure. Missing/corrupt sources
may fail before run reports are created. Failed validation reports never imply
that a database has been published.

## Planned layout

`sql/staging/` holds shared transformations; `sql/marts/` holds final table assembly.
`src/casino_pipeline/analysis/` and `model/` will provide analytical intermediates.
These files are explicitly marked placeholders until their stages are implemented.
`config/action_proposals.csv` starts empty; no recommendations are fabricated.

See [mart contracts](docs/mart_contracts.md), [methodology](docs/methodology.md)
and [app handoff](docs/app_handoff.md). Generated output is ignored by Git.
