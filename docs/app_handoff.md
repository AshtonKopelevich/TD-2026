# Flask app handoff

Stage 2 produces a queryable, standalone `output/casino.duckdb` database.

Currently available: `marts.mart_machine_daily` (55,092 rows in the default release).
The key is `(machine_id, gaming_date)`. `metadata.mart_columns` lists column types
and nullability. `metadata.build_manifest` and `diagnostics.validation` store JSON
documents identifying and validating the build. No raw/staging views are published.
The other 13 contracted marts will be added in subsequent stages.

The app should open a completed artifact using `duckdb.connect(path, read_only=True)`
and parameterize filter values. Use connections per request/worker rather than a
shared mutable global connection.

The pipeline builds/validates a separate file before publication. App readers
must close the old file before it is replaced, particularly on Windows. Do not run
a writer against the file used by separate app reader processes. Publication and
refresh is an explicit stop/close, rebuild, reopen operation. Failed builds preserve
the previous database. Failed attempts appear in versioned reports, not as a new
published database.

## Example filtered query

```python
import duckdb

with duckdb.connect("output/casino.duckdb", read_only=True) as con:
    rows = con.execute("""
        SELECT machine_id, gaming_date, x_m, y_m, coin_in_usd, theo_usd,
               scheduled_seconds, available_seconds
        FROM marts.mart_machine_daily
        WHERE zone_id = ? AND gaming_date BETWEEN ? AND ?
        ORDER BY gaming_date, machine_id
    """, [zone_id, start_date, end_date]).fetchall()
```

Dates are gaming dates, not midnight calendar days. Coordinates are metres and
may be NULL. Money is returned as Python Decimal values; the Flask serialization
layer must choose an explicit JSON representation. Aggregate measure components
before dividing for period-wide ratios. A machine may change position over time.
