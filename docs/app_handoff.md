# Flask app handoff

Stage 5 produces a queryable, standalone `output/casino.duckdb` database.

Currently available:

| Table | Unique key | Default rows |
| --- | --- | ---: |
| `marts.mart_machine_daily` | machine_id, gaming_date | 55,092 |
| `marts.mart_machine_month` | machine_id, month_start | 1,834 |
| `marts.mart_floor_daily` | gaming_date | 181 |
| `marts.mart_zone_daily` | zone_id, gaming_date | 1,267 |
| `marts.mart_benchmark_month` | month_start | 6 |
| `marts.mart_player_month` | player_id, month_start | 148,893 |
| `marts.mart_visits_month` | month_start, home_region, age_band, opening_tier | 180 |
| `marts.mart_comps_daily` | gaming_date | 181 |
| `marts.mart_comps_tier_month` | opening_tier, month_start | 18 |
| `marts.mart_tickets` | operation_id | 1,226 |
| `marts.mart_downtime_hourly` | machine_id, hour_start_utc | 1,321,908 |

`metadata.mart_columns` lists column types
and nullability. `metadata.build_manifest` and `diagnostics.validation` store JSON
documents identifying and validating the build. No raw/staging views are published.
The other three contracted marts will be added in subsequent stages.

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

## Stage-three semantics

- Machine months span the first/last observed active date. They count distinct
  locations/configurations rather than assigning a misleading single location.
  Statistical fields are NULL with `statistical_status='not_implemented'`.
- Floor contribution subtracts machine costs AND technician labor exactly once;
  it is contribution after supplied costs, not complete business profit.
- Multiple event names are joined with ` | ` after aggregation. Their presence
  is descriptive, not an assertion of causal effects or forecast-time knowledge.
- NOAA weather is joined on the calendar date equal to gaming_date. Quality-flagged
  quantities become NULL; a trace-precipitation flag distinguishes trace from
  ordinary zero where the measurement passed its source quality checks.
- Zone entries are sensor crossings, not people. `counter_expected_seconds`
  assumes all sensors observed in this release operate throughout each gaming
  day. `counter_schedule_basis` labels that inference. `counter_missing_seconds`
  counts absent feed hours; it is distinct from observed offline/partial coverage.
  A wholly absent sensor cannot be inferred. Statuses: complete, partial, offline,
  missing (no feed rows for a known sensor roster that day), no_sensor.
- Benchmark amounts map Missouri handle to coin-in and adjusted gross receipts
  to the labeled house-win comparison. They describe another jurisdiction.
  State, property, and category totals are never added together.
- Indices use January of the same year as 100. Missing/zero January baselines
  yield NULL; partial property months yield NULL property indices. External data
  retain publication/retrieval provenance and are retrospective context only.

## Stage-four semantics

- Player-month rows preserve the observed source player-month grain. `tier_end`
  is an attribute; comp cohorts use the fixed `opening_tier`, even after promotion.
  Unknown demographic values become `Unknown`.
- `tracked_net_usd` is payout minus wagering. `actual_tracked_loss_usd` is its
  negative; players can have negative actual losses. Player gaming outcomes cover
  carded play, not the entire floor.
- Visits are observed property visits, not Las Vegas trips. All linked sessions
  and receipts follow the visit's first gaming date into its cohort month. This
  deliberately differs from activity-month player/comp totals. `complete_gaming_visits`
  is the winner-share denominator: incomplete and nongaming visits are excluded.
  `unique_players` cannot be summed across months.
- POS/ledger event timestamps convert to local time before subtracting six hours.
  Events exactly at the next gaming-day boundary belong to the next day. The
  final-boundary award is excluded from Jan-Jun totals and recorded in coverage.
- Comp costs come from verified ledger redemptions and are already inside POS
  COGS. `tracked_contribution_usd` subtracts COGS once, never comp costs again.
  Spend means signed actual gaming loss plus linked POS cash, excluding comp face value.
- Daily comp ratios and tier-month ratios use sums. Cost/loss and cost/spend are
  NULL for zero or negative denominators; status fields distinguish those cases.
- Points balances start at the annual zero balance plus ledger changes. Monthly
  balances carry forward for inactive cohorts; new accounts enter at zero.
  `cohort_players` counts enrolled accounts at month end, while `active_players`
  counts distinct accounts with gaming, linked POS or ledger activity that month.
- `above_expected_loss_flag` and `policy_change_candidate` remain NULL. Configuration
  statuses distinguish unavailable definitions from computed false findings.
- `diagnostics.player_outcomes` is for the build's full window. Winner and
  concentration metrics first aggregate by player across months. Top 1%/10% shares
  describe gross positive player losses among gaming players, not unstable shares
  of signed net loss. Recalculate from player-month data for different filters.
- `diagnostics.guest_coverage` reports out-of-window ledger events, excluded
  first-visit cohorts and carded POS without a visit. Such receipts still count in
  player/comp economics, but not visit spending. Positive-cost redemptions without
  verified POS links currently fail validation rather than silently dropping costs.

Example tier comparison for selected complete months:

```sql
SELECT opening_tier,
       SUM(comp_cost_usd) AS comp_cost_usd,
       SUM(actual_tracked_loss_usd) AS actual_tracked_loss_usd,
       CASE WHEN SUM(actual_tracked_loss_usd) > 0
            THEN SUM(comp_cost_usd) / SUM(actual_tracked_loss_usd)
       END AS comp_cost_per_actual_loss
FROM marts.mart_comps_tier_month
WHERE month_start BETWEEN ? AND ?
GROUP BY opening_tier;
```

## Stage-five semantics

- Tickets include all operation types overlapping the horizon and retain original
  timestamps and full direct costs. A fault category does not imply all downtime
  was preventable. Do not sum ticket durations to obtain machine downtime: tickets
  overlap. Their repair costs are already in machine-day costs, not extra expenses.
- Response begins at outage opening; repair begins when work starts. Open tickets
  retain NULL completion measures. Before/after comparisons use seven complete
  gaming dates on either side, excluding opening/restoration dates. Flags expose
  truncation, changed position/configuration and competing faults.
  `theo_rate_change` means after minus before, in dollars per available hour.
- Hourly keys are UTC. `scheduled_seconds` is the installed portion of an hour.
  Overlapping intervals are unioned with fault precedence over planned work.
  Attribution is capped at meter-reported downtime; remaining meter downtime is
  other. `outage_attribution_status` exposes ticket/meter disagreement rather
  than adding conflicting durations. Hourly theo is derived from the effective RTP.
- Healthy reference hours require a fully available day, no fault that day and
  two stabilization days after a known install or new placement/configuration.
  The release's initial placement boundary does not imply an old machine moved.
  `reference_hours` and `neighbor_count` expose coverage. References include nearby
  future dates, so estimates are retrospective, not forecasts.
- Other-bank peers in the same zone provide contemporaneous demand. Separate
  target/peer reference ratios normalize wagers and theo. Zero observed downtime
  means zero loss; insufficient coverage means NULL. Coverage diagnostics report
  how much downtime was estimated instead of treating uncovered hours as zero.
- Low/high theo bounds use the empirical 95th-percentile absolute one-hour
  pseudo-outage error, scaled by outage duration and floored at zero. They are
  sensitivity scenarios, not calibrated confidence intervals. Validation excludes
  the target's entire gaming day from its reference. Band-specific errors fall
  back to the overall sample only with enough cases; otherwise bounds are NULL.
- Hidden downtime remains NULL with not_configured status until BUSY_PEER_THRESHOLD
  is set to a peer occupancy fraction. When configured, three consecutive UTC hours
  of fully available zero play with busy peers form candidates. They do not add
  measured downtime or economic losses automatically.
- `available_tech_staff_hours` is overlapping rostered coverage in the zone plus
  floor-wide staff, not idle capacity. It repeats per machine: never sum it across
  machines. Missing roster dates give NULL; known dates with no matching techs give zero.
- Loss estimates are gross opportunity estimates. Player substitution and net
  floor loss are not identified; do not present these as guaranteed action benefits.
