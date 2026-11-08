# Final delivery and refresh

The pipeline implements all eight planned stages and creates fourteen physical
mart tables in output/casino.duckdb. The action table can validly have zero rows
while config/action_proposals.csv contains no proposals.

## Build and inspect

```powershell
uv sync --extra dashboard
uv run python run_all.py --verify-hashes --export parquet --check-dashboard
```

The full build validates raw sources, transforms marts and publishes only after
data validation passes. The preceding published artifact remains on failed data
validation or a publication lock. Stage eight then reopens the artifact read-only,
checks all fourteen tables against their embedded schemas/keys/counts, generates
a dictionary and performs optional export/consumer checks.

The --check-dashboard flag requires the dashboard extra. It sends requests through
Flask's test client to the landing page, seven chapters, a machine drill-down and
a bank/date-filtered explorer. It starts no server and sends no external messages.
The pipeline does not edit the dashboard. Route errors are recorded as consumer
integration failures; the valid database is still available. See the report for
the distinction between artifact validity and consumer readiness.

For a database already built, avoid rerunning analyses:

```powershell
uv run python run_all.py --handoff-only
uv run python run_all.py --handoff-only --export parquet
uv run python run_all.py --handoff-only --export csv
uv run python run_all.py --handoff-only --check-dashboard
```

Handoff-only needs no source data for artifact inspection/export. The current
dashboard may additionally use source layout/catalogue files; its owner controls
those optional fallbacks and deployment choices.

## Files to deliver

1. output/casino.duckdb: the complete query artifact, including diagnostics and metadata.
2. docs/app_handoff.md: consumer query patterns and metric semantics.
3. docs/methodology.md and docs/mart_contracts.md: definitions and limitations.
4. docs/action_proposals.md plus the intended proposal configuration, if funding actions.
5. The current run's manifest.json, validation.json, handoff.json, handoff.md and
   data_dictionary.md, found through output/reports/latest_handoff.json.
6. Optional exports through output/exports/latest.json and their checksum manifest.

The generated output directory is ignored by Git. Copy these artifacts explicitly
or deliver them through the team's chosen artifact channel. Source code, dependency
lock and documentation remain in version control; no automated commit or upload occurs.

## Export semantics

Parquet uses ZSTD and preserves decimal/date/boolean types. CSV is UTF-8 with a
header, ISO dates, UTC timestamps with Z suffix and empty missing fields; it loses
type information. Use the dictionary rather than guessing IDs or monetary types.
Both formats use manifest column order and key order. Export files are verified
before replacement; the latest export pointer advances only after the requested
set completes. The empty action mart is exported with its schema/header.

Hourly exports are substantially larger than aggregate marts. The Flask app can
query the database directly; no export is necessary for ordinary app use.

## Rebuild evidence

A full stage-eight build fingerprints the prior artifact, then compares its
analytical table contents with the new artifact when source release/configuration/
engine match. Hashes are order-independent, normalize DOUBLE to eight decimal
places and high-scale DECIMAL to six, and exclude prediction_frozen_at_utc because
the actual freeze time deliberately changes. This is a diagnostic equivalence
check under declared tolerances, not a proof of byte-for-byte equality or a second
full rebuild. Changed inputs or engine versions are labeled separately.

The source manifest and optional source-file verification use SHA-256. Output
database/exports also have SHA-256 checksums. Pipeline source/SQL/lockfile digest
and Python/NumPy/DuckDB versions are recorded in the build manifest.

## Refreshing Flask

The app prefers CASINO_DB, otherwise output/casino.duckdb, then the placeholder
casino.duckdb in the repo root. Point CASINO_DB explicitly to the intended artifact
when deploying. Close app database connections before replacing the file,
particularly on Windows; rebuild, then restart/reopen the app against the new build.
Each request should use its own read-only connection and parameterized filters.

Runtime smoke checks do not certify presentation. The owner should confirm dates,
bank/guest filters, model validation and evidence links in the browser, and address
the interpretation differences listed in docs/app_handoff.md. In particular, show
unknown estimates as unavailable, distinguish gross from net downtime loss, and
do not interpret an empty proposal file as a funded recommendation.

The initial delivery passed all 320 build checks and 48 standalone artifact
checks, matched the preceding analytical artifact, and produced 14 Parquet
exports. Two Flask routes initially failed on the reserved SQL alias `share`;
quoting that alias in dashboard/pages.py resolved both failures. All ten checked
routes now return HTTP 200. Only the two failed routes were retried; the JSON
handoff retains the earlier failures and retry results.

After fixing a failed consumer route, retry only previous failures with
`uv run --extra dashboard python run_all.py --recheck-dashboard-failures`.
This verifies the database checksum and updates the existing handoff report
without rebuilding marts or repeating exports.
