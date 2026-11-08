# Methodology and implementation status

Stage 1 inventories source schemas and validates source identity/declared keys.
Stage 2 materializes the machine-day mart; stage 6 adds statistical evidence and
descriptive classifications. These do not establish causal conclusions.

Machine-day raw cents and squared-bet totals supply all-play and tracked meters.
Prepared daily views supply machine cost components and zone labels. Effective
game math supplies configuration theme, RTP and payout multiplier variance.
Floor locations supply the slot hierarchy and coordinates. LEFT joins preserve
unmatched active records so validation fails instead of silently dropping them.

Only active days in the configured historical window are included. Source keys,
interval coverage and identity checks ensure one placement/configuration per day.
Scheduled time is the on-floor portion of the gaming day, reconciled to placement
overlap; full calendar day length is separately retained. Ratios return NULL for
zero denominators. Negative house win is preserved.

Dollar meters use decimal cents conversion. Theo is stored at eight dollar
decimal places, as contracted, with maximum rounding of 0.000000005 dollars per
value; the source can contain finer fractions of a cent. Prepared theo has four
dollar decimal places and reconciles within 0.00005001 dollars. Prepared hours
reconcile within 0.000001 hours. Actual contribution reconciles within half a
cent. Machine costs are summed once, without reapplying cost_rules.

Outcome variance in dollars squared is configuration payout-multiplier variance
times sum_bet_squared (cents squared), divided by 10,000. This is an input to a
future luck test, not a computed verdict.

Defaults live in `src/casino_pipeline/constants.py` and are snapshotted in each
manifest. Eligibility cutoffs and operational triggers are sensitivity parameters,
not guarantees. Uncalibrated definitions remain `None`; future analytical code must
not silently generate flags that depend on them.

## Stage 3: descriptive marts

Machine-month values sum additive daily measures before calculating ratios.
Period bounds are the first/last active date observed that month. Distinct slot
and configuration counts preserve moves/settings changes. Outcome variance is
summed, but z/p/q values and bootstrap intervals remain NULL until stage 6.

Floor totals aggregate validated machine-day records onto the complete source
calendar, then join property POS/costs, independently aggregated events and NOAA
weather. The source `scripts/verify_semantics.py` explicitly defines property
contribution as house win + POS cash - POS COGS - machine costs - technician labor.
Both this formula and the reported property contribution are reconciled. The
weather station is USW00023169; tmax_c is Celsius, prcp_mm is millimeters. The
calendar-date alignment is an approximation to the gaming-day reporting window.
Nonempty NOAA quality flags suppress the affected value; trace rainfall is exposed.

Zone rows cover every source zone with slot nodes on every analysis date,
including zero active machines. Traffic is grouped independently by source UTC
hour into calendar-supplied UTC gaming-day boundaries, preserving DST duration.
Source coverage_minutes supplies observed seconds; entries with offline counters
remain NULL. No schedule/install table for sensors exists: expected seconds use
the distinct release-wide sensor-to-zone roster times the gaming-day length,
explicitly assuming full-day operation throughout the release. Missing feed rows
reduce coverage instead of shrinking its denominator. Missing entire sensors
cannot be detected; a changed sensor scope requires a future schedule contract.
This assumption is labeled in counter_schedule_basis and reported in documentation.

Missouri statewide handle_usd is the wager comparison and agr_usd is reported
adjusted gross receipts; neither is combined with property/category totals.
LVCVA visitor_volume is the Las Vegas visitor comparison. Raw source URLs,
revision/retrieval dates and as-of limitations are retained. Ratios of source
month totals to same-year January totals form indices (January=100). No available
month substitutes for a missing/zero January. Property indices are suppressed
for incomplete observed months; external months retain their full-month scope.
Six months of these associations cannot separate seasonality from trend.

Tests cover independent known-answer sums, overlapping events, technician costs,
zero/missing denominators, duplicate context keys, trace/quality-flagged weather,
offline/partial/missing/no-sensor traffic, DST and multiple sensors per zone.

Statistical methodology and forecast validation will be documented alongside
their implementation. Remaining proposed definitions are in `mart_contracts.md`.

## Stage 4: tracked players, visit cohorts and comp accounting

Player-month rows retain prepared values, independently reconciled against session,
receipt and ledger aggregates at player/month grain. Session counts use distinct
logical session IDs. Region, age band and opening tier come from player identity;
Unknown is an explicit bucket. Protective flags remain unavailable until calibrated.

Each financial source is first aggregated at player/day grain. A union of these
keys drives joins, preserving receipts/redemptions without gaming and preventing
many-to-many multiplication. UTC timestamps become America/Los_Angeles local
timestamps before subtracting six hours; source session gaming dates are checked.
Event time determines ledger attribution, not feed availability time. The source
includes one award exactly at the July 1 boundary; it is excluded, consistent with
the prepared player totals. No timestamp is clamped into the historical window.

Visit cohorts use first observed gaming date. All linked sessions and POS receipts
follow the visit, including activity in later months. Incomplete visits remain in
volume/spend totals but not the complete-gaming-visit winner denominator. Source
foreign keys are validated before attribution. Carded POS without visit IDs remains
in player economics and is separately reported as missing visit coverage.

Ledger redemption links must agree with POS player, receipt identity, cost, face
value and event time; reverse comp links are also checked. All supplied redemptions
pass. Unsupported unlinked/non-POS redemptions fail rather than being silently
treated as zero costs. Tracked contribution is actual loss plus linked POS cash
minus linked POS COGS. Redeemed economic comp cost is already in COGS; face value
is not cash revenue. Uncarded POS is excluded from tracked spend measures.

Tier cohorts are fixed at opening tier, with every source cohort on every month.
Enrolled-account counts use gaming-month end. Active-account counts use distinct
players with session/POS/ledger activity, not summed daily counts. Tier promotions
do not transfer either balances or activity between opening-tier cohorts.

Redeemable balances start at zero annually; opening_lifetime_points affects tier
identity, not redeemable points. For later analysis start months, prior same-year
ledger activity initializes the balance. Daily and monthly snapshots carry forward
through inactivity; newly enrolled accounts enter at zero. Individual balances
are checked at grouped event instants so cohort totals cannot hide an overdraft.
Snapshots and changes reconcile independently to annual ledger sums. Stage 4
requires complete months in one year; it does not prorate prepared player months.

Theo intermediates retain ten dollar decimal places from source cents; output
comp theo uses eight. Per-player source prepared theo reconciles within 0.00005001
dollars. Daily/monthly comp theo reconciliation allows at most 0.00000001 dollars
per aggregated daily/tier row for their independent rounding. Other financial and
points reconciliations are exact at their specified precision.

Comp ratios are ratios of sums. Cost per actual loss and spend are unavailable
when those signed denominators are nonpositive; statuses identify zero versus
negative values. Policy-change flags remain NULL while the method is unconfigured.
Setting a method name alone does not implement a detector: status becomes
not_implemented. Protective thresholds follow the same explicit availability rule.

Fixed-window player diagnostics aggregate each player's months before counting
winners. Gross positive losses and gross winnings are separate; concentration
uses the largest ceil(1%/10% of gaming players) gross-loss amounts, divided by total
gross positive loss. No positive loss denominator means NULL shares. This avoids
presenting a signed-net ratio as a conventional concentration percentage.

## Stage 5: operations and downtime

Operations retain original timestamps and direct costs. Window-clipped intervals
only allocate outages; incomplete tickets are not assigned fictional completion
timestamps. Ticket before/after windows use seven complete active gaming dates
on either side. Context changes, competing faults and insufficient dates are
explicitly flagged. Rate changes are descriptive dollar-per-available-hour gaps.

Installed machine-hours join effective placements, game math and slot hierarchy.
Scheduled seconds are overlap with the placement, calendar day and UTC hour.
Hourly theo is coin-in times configured expected hold and reconciles to daily theo.
Outage interval endpoints split each machine-hour into nonoverlapping segments;
fault takes precedence over planned work. Allocations are capped at authoritative
meter downtime. Excess ticket coverage and unexplained meter downtime remain
visible, with remaining meter seconds assigned to other downtime.

Peer pools aggregate healthy machines by zone/hour and subtract the entire target
bank. Healthy reference days are fully available, fault-free, and at least two
days after known installation or a subsequent placement/configuration boundary.
The initial release boundary does not reset stabilization for old machines.
References use the same placement/configuration and four-hour local band within
28 dates on either side. At least three other-bank peers and twenty matched
healthy hours are required. Separate target-to-peer wager/theo ratios multiply
current peer hourly rates and target unavailable hours. Ratios are weighted sums
of matched target/peer exposure, not averages of hourly ratios.

Reference calculations first aggregate day/band values, then use rolling windows;
there is no quadratic machine-hour self-join. Future nearby reference dates are
allowed for this retrospective analysis. These values are not forecast features.

Up to 2,000 deterministic hash-selected healthy pseudo-outages exclude their
entire target day from reference fitting. Diagnostics retain actual/predicted theo,
MAE and absolute-error quantiles overall and by band. At least thirty cases are
needed per error estimate; sparse bands fall back to the overall sample. Low/high
loss scenarios use +/- the 95th-percentile absolute hourly error times outage hours,
floored at zero. These are not probability-calibrated intervals or additive
confidence bounds. Report uncovered downtime and gross estimates separately;
substitution and net floor loss have not been identified.

Hidden-downtime logic is implemented but defaults to unavailable until busy-peer
occupancy is calibrated. Configured detection requires three consecutive fully
available zero-spin/zero-wager UTC hours with enough busy peers. It is a candidate
flag only. Staffing is interval-overlap rostered zone plus floor-wide technician
hours, repeated as context for machines rather than additive across machines.

Only two targeted tests were used for stage 5: known overlapping fault/planned
intervals, peer estimates and pseudo-outages, plus partial installation and missing
peer coverage. The failed peer check was rerun after fixing its schedule reference;
the earlier stage suites were not rerun. One complete build reconciled actual data.

## Stage 6: machine evidence and classifications

Approximate z = sum(house win - theo) / sqrt(sum(game payout-multiplier variance
times squared bets in dollars)). Configuration-specific daily variance already
covers all play, including uncarded play. Eligibility uses 60 active/30 wager dates
for the full window and 21/14 for monthly tests. Zero variance and inadequate
exposure give NULL tests. Two-sided p-values use erfc; BH q-values are computed
within the eligible full-window family and separately within each calendar month.
Family sizes are reported even for ineligible rows. BH assumes independence or
suitable positive dependence; no overall FDR claim spans all seven families.

Nonoverlapping seven-day calendar blocks are built within uninterrupted placement
episodes, preserving each day's residual and wagering together. Each episode is
resampled with its original number of complete blocks, so configurations/locations
are not freely mixed. Remainders are discarded with covered-day counts exposed;
at least eight blocks and 80% day coverage are required. The seed derives from a
stable hash of the configured seed, machine and period. 10,000 resamples are processed
in bounded batches. Zero-denominator resamples are counted and omitted; fewer than
95% valid draws leaves the interval unavailable. Degenerate block variation also
gives no interval. Percentile intervals describe the covered-data hold residual,
not a dollar interval or a bootstrap hypothesis-test p-value. Eight weeks cannot
fit in a month, so monthly intervals remain NULL even when monthly CLT tests qualify.

Normalized daily residuals are screened for lag-one, weekend, day-of-month,
temperature, observed traffic and event association. Lag pairs never bridge a gap
or placement change. Correlations require twenty valid pairs; traffic requires
80% source coverage. Absolute correlation >=0.30 is a warning, not a formal
significance threshold. A single day contributing over 25% of variance or wagering
also warns. Neither small correlations nor a bootstrap CI establish independence,
stationarity or normal approximation accuracy. High-volatility games may retain
rare-event uncertainty that neither method captures from observed history.

Daily peer pools exclude the target and use only positive available exposure.
Zone rates on matching dates are weighted by the target's hours. Target-to-peer
ratios use the same covered dates, rather than comparing a covered benchmark with
all target days. Eligibility requires three peers per date, thirty covered dates,
80% coverage and full-window exposure minima. Weak-demand flags require at least
20% gaps in both wager and theo rates. Quiet-zone location flags require a 20%
zone-to-floor wager-rate gap, a machine near its zone benchmark, and below-floor
machine wagering. Peer/floor context is descriptive and does not fully control
game mix. Bank-level and placement summaries are retained for further investigation.

Unavailable time >=5% of scheduled on-floor time triggers a downtime flag after
60 dates. Repair association requires two comparable fault tickets, with at least
half improving theo/hour by 20%. These thresholds are sensitivity parameters.
Expected contribution after supplied machine costs per available hour determines
adjusted ranks; actual house win determines the GM ranking. Ties use machine IDs.

Inspection flags use q<=alpha, suppressed for dependence/concentrated-exposure
warnings. Luck compatibility requires a non-rejection and, where available, a
bootstrap interval spanning zero. A corrected CLT decision and unadjusted block
interval can disagree simply because their multiplicity treatments differ; this
is explicitly surfaced, not interpreted as a second significant test. Classification
preserves overlapping flags, uncertainty and insufficient data. It never infers
replacement value, fraud, or causality from a p-value. Verdicts are fixed-window
artifacts and are not automatically recalculated for app filters.

## Stage 7: forecast selection and proposal costing

Two candidates compete: weekday means and least-squares regression with intercept,
six weekday indicators, holiday, known citywide-event and known property-event
flags. Features use source calendar holidays plus an explicit July 4 future flag.
Events qualify only if announced by the fit origin, including for all future
dates in that prediction block. Weather, tourism revisions, actual holdout lags,
repairs and recommendation outcomes are not features. Nonnegative prediction
clipping and cent rounding apply consistently before selection/evaluation.

Candidate fits query Jan-Mar targets only and materialize April predictions before
joining April actuals. Minimum April MAE selects the architecture, with weekday
means winning exact ties. The chosen architecture and a constant-mean baseline
refit Jan-Apr and materialize May-Jun predictions before test evaluation. Holdout
MAE is reported overall and by weekday; failure to beat the baseline is a valid
result and does not trigger retrospective reselection. The same architecture
then refits Jan-Jun for July 1-30, with no action applied to the baseline demand.

Model parameters, prediction snapshots, feature cutoffs, candidate errors and
selection are retained. prediction_frozen_at_utc records the actual build time;
forecast_origin is a simulated 2025 cutoff, not evidence of a genuine historical
2025 forecast. No July event listing is supplied, so flags reflect limited source
coverage. A different forecast horizon requires updating future holiday inputs.

Proposal configuration is explicit and content-fingerprinted. Catalogue prices,
quantity limits, leads and incompatibility groups are authoritative. Targets resolve
against placements active at horizon start. Bank/manufacturer downtime expands to
affected machines. Operating opportunity and incremental uplift are reduced for
action downtime separately; proposal cash costs are subtracted once. Scenario
assumptions must exclude charges already present in the proposal budget. These
benefits are not statistical effect estimates or confidence intervals.

Selected portfolios must stay within $100,000 and three action types, excluding
preserved funds. Catalogue quantities aggregate across selected rows. Move and
replacement conflicts expand bank membership; comp policy alternatives conflict
globally. Promotion dates and durations must respect lead times and cannot overlap.
Unknown information benefits remain NULL. Forecast target allocation requires an
explicit share and is context only, not inferred uplift. Joint effects, substitution
and destination feasibility require separate evidence/operational review.

The default empty CSV produces a valid empty action mart, no_proposals status and
the entire budget unallocated. This is a configuration state, not a finding that
preserving all funds is optimal. Three focused tests cover holdout isolation,
lease/downtime economics and conflicts, and empty-proposal publication.

## Stage 8: standalone delivery

The published database is reopened read-only and checked against its embedded
manifest for all fourteen physical marts, keys, column types/nullability and row
counts. Representative parameterized consumer queries verify standalone use.
Optional CSV/Parquet exports are streamed in key order, verified and checksummed;
the delivery includes a generated column dictionary and per-build handoff report.
Rebuild comparison uses the documented normalized, order-independent diagnostic
hashes rather than asserting byte-for-byte equality.

Two focused tests cover export round trips (including empty tables, decimals,
NULLs and timestamps) and artifact inspection/content fingerprints. The final
real-data delivery passed 320 build checks and 48 artifact checks and matched the
preceding build. Ten Flask routes passed; two required quoting one reserved SQL
alias and were retried individually. Route checks establish query compatibility,
not visual correctness or approval of dashboard interpretations.
