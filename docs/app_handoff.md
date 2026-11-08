# Flask app handoff

Stage 1 does not yet produce a queryable mart database.

The planned deliverable is `output/casino.duckdb`, containing physical tables in
the `marts` schema, plus `diagnostics` and `metadata`. Names follow the contracts,
for example `marts.mart_machine_daily`. Raw/staging source-file views will not be
dependencies of the published artifact.

The app should open a completed artifact using `duckdb.connect(path, read_only=True)`
and parameterize filter values. Use connections per request/worker rather than a
shared mutable global connection.

The pipeline will build/validate a separate file before publication. App readers
must close the old file before it is replaced, particularly on Windows. Do not run
a writer against the file used by separate app reader processes. Publication and
refresh lifecycle will be implemented with the first persisted mart in stage 2.
