# Proposed mart contracts

Status: all fourteen marts and the stage-eight artifact/export/handoff tooling are implemented. The action mart contains the configured July pilot portfolio; see action_evidence.md and action_proposals.md. Protective/comp-change flags remain unavailable until configured and implemented. Hidden-downtime detection requires a configured busy-peer threshold. Current verification/consumer status is in output/reports/handoff.md.
Scope: the 14 marts in Dashboard_Royale_Team_Plan_v2.pdf. No presentation-tool requirements.
Source root: dashboard-royale-main/data/. Source files remain unchanged.

## 1. Shared conventions

- Default historical window: 2025-01-01 through 2025-06-30 inclusive. Forecast horizon: July 1-30, 2025.
- Periods are explicit columns. No monthly row inherits a full-window statistical verdict.
- Primary delivery is physical tables in the marts schema of output/casino.duckdb. Optional typed Parquet and UTF-8 CSV exports contain the same rows/columns. CSV dates are ISO dates; timestamps are ISO UTC; missing values are empty fields, never zero or the string "None". Database/Parquet schemas are the type authority. Stage 1 does not yet publish mart tables.
- SQL types below: ID/TEXT = VARCHAR; DATE = DATE; UTC = TIMESTAMP (values always UTC); COUNT = BIGINT; MONEY = DECIMAL(24,2) dollars; THEO = DECIMAL(28,8) dollars; NUMBER = DOUBLE; FLAG = BOOLEAN. A stated nullable field may be NULL; all other fields are required.
- Month keys use month_start DATE (first day), not free-form strings.
- Keys must be unique and non-null. Foreign-key references must resolve unless an explicitly documented unknown bucket applies.
- Ratios use sums of components, not averages of row ratios. Export the underlying components as well as convenience ratios. Ratios are fractions, not percentages.
- Division by zero returns NULL. Loss-based and spend-based comp ratios return NULL for denominators <= 0 and carry an explicit status. Negative house win/player loss is retained.
- Money converted from cents is divided by decimal 100, not integer division. Preserve source theo precision. Sum first; round MONEY fields only at export. Statistical calculations may use floating point internally.
- House win = coin-in - payout. Player net = payout - coin-in. Actual player loss = coin-in - payout (signed, not clamped to zero).
- Actual machine contribution = house win - supplied machine costs. Expected machine contribution = theo - the same costs. Neither includes unsupplied overhead.
- Gaming date is the date of local timestamp minus six hours, after converting UTC to America/Los_Angeles. Use source gaming_date/calendar boundaries where supplied. Do not subtract six hours in UTC to infer local gaming dates.
- Time intervals are [start, end). NULL placement end means open-ended. Hourly keys use UTC to distinguish repeated local hours.
- Distinguish scheduled time ON FLOOR (machine_day.scheduled_seconds) from the full calendar gaming-day duration. Availability uses on-floor scheduled time; partial installation/retirement days must not be treated as full days.
- Raw views keep inactive rows. Machine performance marts use active rows with a valid placement; unmatched active rows fail validation rather than silently disappearing.
- Structural zero: an entity is in scope and no activity occurred in a complete source. Unknown/missing coverage: NULL, with coverage/status fields. Never convert offline traffic to zero.
- Each build writes a manifest with build ID, source release, source-file fingerprints, analysis window, code version when available, parameters, seed, schemas, row counts and validation results. These need not be repeated on every output row.
- Every mart has a companion dictionary describing formulas, units, nullability, sources and additivity. Diagnostics record unavailable estimates and excluded observations.

## 2. Reusable column groups

These groups expand into concrete columns wherever referenced below. They are not nested objects.

### Machine identity and position (P)

| Columns | Type | Meaning |
| --- | --- | --- |
| machine_id, location_id, zone_id, bank_id, config_id | ID | Machine and position/configuration for the row's time |
| zone_name, manufacturer, theme, lease_class | TEXT | Source labels |
| x_m, y_m | NUMBER, nullable | Slot coordinates in metres; missing coordinates do not drop the machine |

### Machine additive measures (M)

| Columns | Type | Meaning |
| --- | --- | --- |
| scheduled_seconds, available_seconds, occupied_seconds | COUNT | On-floor schedule and activity duration |
| paid_spins, carded_spins | COUNT | All spins and tracked subset |
| coin_in_usd, payout_usd, house_win_usd | MONEY | All-play meters |
| carded_coin_in_usd, carded_payout_usd | MONEY | Tracked subset of meters |
| theo_usd, carded_theo_usd, luck_residual_usd | THEO | Expected win and house_win - theo |
| lease_cost_usd, service_cost_usd, power_cost_usd, repair_cost_usd | MONEY | Supplied machine costs; prepared values are authoritative, not charged again from cost_rules |
| machine_cost_usd, actual_contribution_usd | MONEY | Sum of those four costs; house_win - machine_cost |
| expected_contribution_usd | THEO | theo - machine_cost |

### Machine ratios (R)

All NUMBER, nullable when denominator is zero:

- availability_ratio = available_seconds / scheduled_seconds.
- occupancy_ratio = occupied_seconds / available_seconds.
- observed_hold = house_win_usd / coin_in_usd.
- expected_hold = theo_usd / coin_in_usd.
- carded_coin_in_share = carded_coin_in_usd / coin_in_usd.
- coin_in_per_available_hour = coin_in_usd / (available_seconds / 3600).
- theo_per_available_hour = theo_usd / (available_seconds / 3600).
- expected_contribution_per_available_hour = expected_contribution_usd / (available_seconds / 3600).

### Comp economics (C)

| Columns | Type | Meaning |
| --- | --- | --- |
| tracked_coin_in_usd, tracked_payout_usd, actual_tracked_loss_usd | MONEY | Signed actual loss = wagers - payout |
| tracked_theo_usd | THEO | Modeled expected house win on tracked play |
| linked_pos_cash_usd, linked_pos_cogs_usd | MONEY | Receipts/costs linked to tracked players; excludes uncarded POS |
| total_tracked_spend_usd | MONEY | Signed actual tracked loss + linked POS cash; not coin-in or comp face value |
| comp_face_value_usd, comp_cost_usd | MONEY | Redeemed benefit menu value and economic cost from ledger, reconciled to linked POS |
| tracked_contribution_usd | MONEY | Actual tracked loss + linked POS cash - linked POS COGS; comp cost is already inside COGS |
| points_earned, points_redeemed | COUNT | Nonnegative award and redemption quantities |
| points_balance_start, points_balance_end, points_balance_change | COUNT | Redeemable balance snapshots; change = earned - redeemed |
| comp_cost_per_actual_loss, comp_cost_per_total_spend | NUMBER, nullable | Cost / signed denominator, only when denominator > 0 |
| comp_cost_per_coin_in | NUMBER, nullable | Cost / tracked coin-in, only when > 0 |
| theo_per_comp_cost | NUMBER, nullable | Tracked theo / cost, only when cost > 0; secondary diagnostic |
| actual_loss_ratio_status, total_spend_ratio_status | TEXT | positive_denominator / zero_denominator / negative_denominator |

Source redeemable points start at zero each year; opening_lifetime_points is NOT a redeemable balance. Comp face value is not revenue. Unredeemed points are units, not a dollar liability without an explicit valuation assumption.

## 3. mart_machine_daily

- Purpose: reusable machine-day evidence, time filters, floor map, machine/month/scorecard inputs.
- Grain/key: (machine_id, gaming_date); active machine-days only.
- Sources: prepared_daily_view, machine_day, machines, calendar_day, floor_locations; placements/game_math for cross-checks and configuration details.
- Columns: gaming_date DATE; month_start DATE; groups P, M, R; active FLAG (always true); meter_status TEXT; calendar_day_seconds COUNT; configured_rtp NUMBER; volatility_class TEXT; payout_multiplier_variance NUMBER; sum_bet_squared_cents2 NUMBER; outcome_variance_usd2 NUMBER; faults_opened COUNT.
- outcome_variance_usd2 = payout_multiplier_variance * sum_bet_squared_cents2 / 10000. Requires one verified configuration per machine-day; configuration ambiguity fails this derivation, not an arbitrary config selection.
- Day position uses the day's effective placement; source placements begin on gaming-day boundaries. Validate this assumption against actual source intervals.
- Checks: source active-row count reconciles; source meters match prepared dollars; no location join multiplication; 0 <= occupied_seconds <= available_seconds <= scheduled_seconds <= calendar_day_seconds; carded coin-in/spins <= all play; valid config and slot.

## 4. mart_machine_month

- Purpose: monthly machine metrics without reusing the full-window verdict.
- Grain/key: (machine_id, month_start); months with at least one active day.
- Sources: mart_machine_daily; machine statistical module.
- Columns: machine_id ID; month_start, period_start, period_end DATE (period bounds inclusive); active_days COUNT; manufacturer, lease_class TEXT; groups M and R; location_count, config_count COUNT; luck_z_score, luck_p_value, luck_q_value, bootstrap_hold_gap_low, bootstrap_hold_gap_high NUMBER nullable; statistical_status TEXT.
- Sum M; recompute R. Sum outcome variances before computing the monthly z-score. Bootstrap bounds describe SUM(residual)/SUM(coin-in), not dollar totals.
- No single location/config field: machines may move or change settings within a month. No full-window classification column.
- Implemented period_start/period_end are the first/last observed active date. outcome_variance_usd2 NUMBER sums daily variance. Stage 6 adds CLT/BH outputs when monthly exposure meets 21 active/14 wager dates. Bootstrap intervals remain NULL under the eight-complete-week rule, with explicit status.
- Checks: additive values reconcile exactly to daily rows within money rounding tolerance. Monthly multiple-testing correction is separate for each month.

## 5. mart_machine_scorecard

- Purpose: fixed-window comparison of GM ranking, adjusted economics and strength of evidence.
- Grain/key: machine_id; include every machine active at least once in the configured window.
- Sources: machine daily/month, tickets and downtime analytical outputs.
- Columns: machine_id ID; analysis_start, analysis_end DATE; active_days COUNT; groups M and R; naive_rank, adjusted_rank COUNT; naive_bottom_10 FLAG; peer_theo_per_hour, peer_rate_ratio NUMBER nullable; peer_coverage_days COUNT; luck_z_score, luck_p_value, luck_q_value, bootstrap_hold_gap_low, bootstrap_hold_gap_high NUMBER nullable; bootstrap_replicates COUNT; statistical_status TEXT; weak_demand_flag, location_flag, downtime_flag, repair_rebound_flag, hold_anomaly_flag FLAG nullable; luck_compatible FLAG nullable; primary_classification, classification_reason TEXT.
- Naive rank: ascending total house_win. Adjusted rank: ascending expected contribution per available hour, NULL last; machine_id breaks ties deterministically. Neither rank alone proves replacement is beneficial.
- z = SUM(house_win - theo) / sqrt(SUM(outcome_variance_usd2)); zero variance gives NULL. Two-sided normal-reference p-values are approximate; BH q-values cover all eligible machines in this full-window family.
- Bootstrap: 10,000 replicates, seeded, seven-day calendar blocks within contiguous active placement/configuration episodes; no concatenation across off-floor gaps. Report usable block counts and NULL intervals when evidence is insufficient. Bounds are 2.5th/97.5th percentiles of resampled residual/coin-in.
- Block-bootstrap intervals are a sensitivity check, not a source of p-values unless a separately documented null-calibrated test is implemented. A CI spanning zero means luck remains plausible; it does not prove normal operation.
- Peer rate: aggregate other machines' theo and available hours in the same zone on the same dates; exclude the target. bank-based comparisons go in diagnostics. Peer comparisons are descriptive and may reflect game mix.
- Proposed classifications: insufficient_evidence / mixed_evidence / weak_demand_candidate / location_associated / downtime_associated / repair_associated / hold_inspection_lead / luck_compatible / no_clear_issue. Preserve component flags so a single label does not hide overlapping explanations.
- Checks: one verdict window only; ranks unique and deterministic among eligible rates; p/q values in [0,1]; bounds ordered. Classification thresholds are review items below, not silent constants.
- Stage 6 adds outcome_variance_usd2 NUMBER; positive_wager_days, bootstrap_usable_blocks, bootstrap_covered_days, bootstrap_valid_replicates, test_family_size COUNT; clt_eligible/bootstrap_eligible FLAG; clt_status/bootstrap_status/statistical_family TEXT to scorecard and monthly statistical detail (variance was already in monthly). Peer coin/contribution/floor rates, coverage fraction, method/dependence/concentration warnings and comparable/rebound ticket counts expose classification evidence. See methodology and metadata.mart_columns for the complete implemented schema.
- Full-window tests retain 60/30 exposure minima. Peer flags require 3 peers/day, 30 covered days and 80% date coverage. Complete blocks must cover >=80% of days and >=95% of resamples must have positive wagering. Monthly thresholds differ only for CLT; monthly block minima are not relaxed.

## 6. mart_floor_daily

- Purpose: all-floor demand/context and the historical forecast target.
- Grain/key: gaming_date; every calendar day in the historical window, including zero activity if genuinely observed.
- Sources: property_day, calendar_day, machine daily; weather_daily and events as separately aggregated context.
- Columns: gaming_date, month_start DATE; weekday_index COUNT (Monday=0); is_weekend FLAG; federal_holiday TEXT nullable; events_active TEXT nullable; active_machines COUNT; scheduled_machine_hours, available_machine_hours, occupied_machine_hours NUMBER; coin_in_usd, payout_usd, house_win_usd MONEY; theo_usd THEO; carded_coin_in_usd MONEY; carded_coin_in_share, coin_in_per_active_machine_day NUMBER nullable; pos_cash_usd, pos_cogs_usd, comp_cost_usd, machine_cost_usd, tech_labor_cost_usd, actual_floor_contribution_usd MONEY; weather_temperature_max_c, weather_precipitation_mm NUMBER nullable; weather_status TEXT.
- Resolved from source verification code and numerical reconciliation: actual_floor_contribution_usd = house win + POS cash - POS COGS - supplied machine costs - tech labor. Labor is separately reported and subtracted once.
- Weather is context keyed by local calendar date matching gaming_date; label this approximation (weather reporting window is not necessarily 06:00-06:00). Source units must be verified before converting to the named units.
- Events are joined by local date range after aggregation, never one output row per event.
- Implemented NOAA station: USW00023169; source tmax_c/prcp_mm are Celsius/mm. Nonempty quality flags suppress the affected measure. Additional nullable weather_precipitation_trace FLAG preserves a source trace-rainfall indicator.
- Checks: 181 default rows; calendar complete; floor machine meters reconcile to machine daily; contextual joins preserve row count. Weather is not a default forecast feature.

## 7. mart_zone_daily

- Purpose: spatial demand and traffic coverage.
- Grain/key: (zone_id, gaming_date); all machine-hosting zones crossed with historical dates, including days with zero active machines.
- Sources: machine daily, zone_traffic_hourly, floor_locations, calendar_day.
- Columns: zone_id ID; zone_name TEXT; gaming_date, month_start DATE; active_machines COUNT; scheduled_seconds, available_seconds, occupied_seconds COUNT; coin_in_usd, house_win_usd MONEY; theo_usd THEO; coin_in_per_available_hour, theo_per_available_hour NUMBER nullable; entries_observed COUNT nullable; counter_observed_seconds, counter_expected_seconds COUNT; counter_coverage_ratio NUMBER nullable; traffic_status TEXT.
- Independently aggregate traffic by zone/gaming day and machine measures by zone/gaming day, then join. Counter expected coverage uses documented sensor scope/operating schedule, not simply row count.
- Traffic entries count crossings, not people. Partial observations remain partial; no automatic scaling to a full day. All-offline entries are NULL.
- No authoritative sensor schedule exists. Implemented expected coverage assumes release-wide sensor roster x full gaming-day duration, labeled counter_schedule_basis TEXT='inferred_full_day_release_roster'. Additional sensor_count COUNT and counter_missing_seconds COUNT distinguish absent feed hours from offline/partial reported hours. Missing entire sensors are not discoverable. Traffic statuses: complete/partial/offline/missing/no_sensor.
- Checks: zone sums reconcile to machine daily; observed coverage <= expected; traffic not multiplied by machines; zero active-machine zones have zero machine totals and NULL exposure ratios.

## 8. mart_visits_month

- Purpose: distinguish recorded-visit volume from gaming intensity for tracked guests.
- Grain/key: (month_start, home_region, age_band, opening_tier). Unknown demographic values use an explicit Unknown bucket.
- Sources: trips, sessions aggregated by observed_visit_id, players, receipts aggregated by observed_visit_id.
- Columns: key fields as DATE/TEXT; observed_visits, complete_visits, incomplete_visits, visits_with_gaming, winning_visits COUNT; unique_players COUNT; visit_assigned_coin_in_usd, visit_assigned_payout_usd, visit_assigned_player_net_usd, visit_assigned_pos_cash_usd MONEY; visit_assigned_theo_usd THEO; coin_in_per_visit, winner_share_complete_visits NUMBER nullable.
- A visit belongs to the gaming month containing its first observed activity. All linked play/receipts for that observed visit follow it into that month, even if the visit crosses a month boundary. Names emphasize this is a visit cohort, not activity-month totals.
- Winning-visit share uses complete visits with recorded gaming only; a complete non-gaming visit is not counted as a gaming break-even outcome.
- Implemented additional complete_gaming_visits COUNT exposes that denominator. Unlinked carded POS remains in player economics and is reported in diagnostics.guest_coverage, not invented as visit spending.
- Incomplete visits are counted and labeled; first-visit assignment outside the historical window is excluded and logged. unique_players is not additive across months or segments.
- Checks: trips never duplicated by sessions/POS; complete + incomplete = observed; gaming visits <= observed; linked visit totals reconcile before cohort exclusions.

## 9. mart_benchmark_month

- Purpose: side-by-side trend context; no claim that different jurisdictions/populations are interchangeable.
- Grain/key: month_start; six historical months by default.
- Sources: floor daily, benchmark_state_monthly, city_visitation_monthly. Property/category Missouri files are reconciliation inputs, not added to state totals again.
- Columns: month_start DATE; property_coin_in_usd, property_house_win_usd MONEY; property_active_machine_days COUNT; property_coin_in_per_machine_day NUMBER nullable; missouri_coin_in_usd, missouri_house_win_usd MONEY nullable; las_vegas_visitor_volume COUNT nullable; property_coin_in_index, missouri_coin_in_index, las_vegas_visitors_index NUMBER nullable; missouri_status, visitation_status TEXT; missouri_source_url, visitation_source_url, source_revision, as_of_limitation TEXT nullable.
- Index = month value / first observed January value * 100; zero/missing base gives NULL. Do not fill missing source months or infer seasonality from six points.
- Implemented source mappings: Missouri handle_usd -> coin-in, agr_usd -> reported adjusted-gross-receipts house-win comparison; LVCVA visitor_volume -> visitors. Additional index_base_month DATE, property_observed_days COUNT, property_period_complete FLAG and nullable missouri_retrieved_date DATE document baseline/coverage. Property indices require complete current and January months; no first-available-month fallback. source_revision/as_of_limitation refer to LVCVA.
- Checks: month joins one-to-one; source quantities/units verified before mapping to coin-in/house-win fields; no duplicated benchmark totals. If source lacks a measure, leave NULL with status, never substitute another measure.

## 10. mart_tickets

- Purpose: operational timing and descriptive repair comparisons.
- Grain/key: operation_id; all operation types, not faults alone.
- Sources: operations, machine daily, machines; staffing context aggregated by interval separately.
- Columns: operation_id, machine_id ID; location_id ID nullable; event_type TEXT; controllable_fault FLAG; opened_at_utc UTC; recorded_at_utc, work_started_at_utc, available_at_utc UTC nullable; gaming_date DATE; response_hours, repair_hours, total_outage_hours NUMBER nullable; direct_cost_usd MONEY; before_available_hours, after_available_hours NUMBER; before_theo_usd, after_theo_usd THEO; before_theo_per_hour, after_theo_per_hour, theo_rate_change NUMBER nullable; before_days, after_days COUNT; comparison_status TEXT.
- response = work_started - opened; repair = available - work_started. An incomplete ticket gives NULL completion metrics, not a fabricated close time. Clip outage allocation to source observation bounds, retain original timestamps here.
- Before/after: seven complete gaming dates before opening and after the gaming date containing availability; use active days, flag overlapping faults, moves/config changes and truncated windows. These comparisons are associations.
- controllable_fault means event_type = fault_repair; it identifies the intervention category, not a proven preventable fraction.
- Checks: nonnegative elapsed durations; response + repair = total for completed tickets; costs counted once; outage duration is not additive across overlapping tickets.
- Stage 5 adds truncated_window, context_changed and overlapping_faults FLAG fields. theo_rate_change is an absolute dollars-per-available-hour difference, not a relative percentage. Only tickets overlapping the selected horizon are included; original timestamps/costs are preserved.

## 11. mart_downtime_hourly

- Purpose: outage timing, hidden-downtime candidates and estimated counterfactual loss.
- Grain/key: (machine_id, hour_start_utc); one row for each installed source machine-hour, including zero-play hours.
- Sources: machine_hour, placements/game_math, operations, calendar, floor locations and aggregated shift roster.
- Columns: machine_id, location_id, zone_id, bank_id, config_id ID; hour_start_utc UTC; gaming_date DATE; local_hour COUNT; utc_offset TEXT; manufacturer TEXT; scheduled_seconds, available_seconds, occupied_seconds, downtime_seconds COUNT; coin_in_usd, payout_usd MONEY; theo_usd THEO nullable; fault_downtime_seconds, planned_downtime_seconds, other_downtime_seconds COUNT; neighbor_count COUNT; neighbor_available_hours, usual_rate_ratio NUMBER nullable; estimated_lost_coin_in_usd MONEY nullable; estimated_lost_theo_usd, lost_theo_low_usd, lost_theo_high_usd THEO nullable; hidden_downtime_flag FLAG nullable; estimate_method, estimate_status TEXT; available_tech_staff_hours NUMBER nullable.
- Scheduled seconds are overlap of installed intervals and the UTC hour; downtime = scheduled - available. Do not assign a full 3600 seconds to partially installed hours.
- Hourly theo = hourly coin-in * (1 - effective RTP) only where configuration is uniquely valid for the hour; no claim of observed hourly theo when this assumption fails.
- Deduplicate overlapping outages before allocation. Fault/planned/other precedence is configurable and must partition total reported downtime without double counting; unexplained downtime falls into other.
- Peer estimator: other-bank machines in the same zone and same UTC hour, normalized by a nearby healthy-period target/peer rate ratio. Exclude the target. No peers or no healthy reference means NULL estimate with a reason.
- Hours with no reported downtime have estimated losses zero; unavailable methods on outage hours are NULL. Hidden downtime is a candidate flag and is not automatically added to measured downtime/losses.
- Validate through held-out fake outages; report MAE, sample sizes and coverage in diagnostics. Gross loss estimates are not net floor losses. A displacement-adjusted floor-loss estimate requires separate supporting analysis and will not be silently assumed.
- Checks: hourly meters reconcile to machine_day; durations bounded and partitioned; UTC keys unique through DST; uncertainty bounds ordered. Peer windows/thresholds remain review items.
- Stage 5 adds hour_band and reference_hours COUNT, usual_coin_in_rate_ratio NUMBER nullable, ticket_overlap_seconds and unexplained_downtime_seconds COUNT, and hidden_downtime_status, uncertainty_status, outage_attribution_status TEXT. Ticket overlap is de-duplicated and capped by measured downtime; excess stays labeled. Error bounds are empirical pseudo-outage scenarios, not confidence intervals. Busy-peer threshold is a configurable occupancy fraction and remains unset by default. Staffing is rostered context, not idle capacity, and is not additive across machines.

## 12. mart_player_month

- Purpose: tracked gaming outcomes and guest drill-down.
- Grain/key: (player_id, month_start); exactly the observed player-month rows in player_period.
- Sources: player_period; players for stable demographics; ledger for tier history as needed.
- Columns: player_id ID; month_start DATE; home_region, age_band, opening_tier, tier_end TEXT (Unknown allowed); observed_visits, incomplete_visits, sessions COUNT; carded_play_hours NUMBER; tracked_coin_in_usd, tracked_payout_usd, tracked_net_usd, actual_tracked_loss_usd MONEY; theo_usd, luck_residual_usd THEO; linked_pos_cash_usd, linked_pos_cogs_usd, comp_face_value_usd, comp_cost_usd, tracked_contribution_usd MONEY; comps_redeemed, points_earned, points_redeemed COUNT; winner_flag, above_expected_loss_flag FLAG nullable.
- Keep source monthly tier_end as an attribute, not as an event-time tier. Monthly player net/luck formulas match source definitions. Protective flag threshold remains a review choice and cannot be used as a claim of harm.
- Full-window concentration/winner shares must first aggregate by player across selected months. Do not sum monthly distinct players or average monthly winner flags.
- Stage 4 adds protective_status TEXT; above_expected_loss_flag is NULL until configured and implemented. diagnostics.player_outcomes reports fixed-window winners and gross-positive-loss concentration separately from signed net results.
- Checks: source row count and totals reconcile; loss = -net; contribution reconciles without deducting comp twice; compare gaming totals to carded machine meters, with any coverage exceptions reported.

## 13. mart_comps_tier_month

- Purpose: additive cohort comparison of monthly comp economics and balances.
- Grain/key: (opening_tier, month_start). IMPLEMENTED: use the player's opening tier as a fixed cohort, not tier at redemption. This gives gaming, POS, ledger and balances one consistent attribution rule.
- Sources: player month, players, sessions, ledger and POS independently aggregated before joins.
- Columns: opening_tier TEXT; month_start DATE; cohort_players, active_players COUNT; group C; policy_change_candidate FLAG nullable; comparison_status TEXT.
- Include all opening-tier cohorts for every month, including cohorts with zero monthly activity but nonzero point balances. cohort_players counts enrolled accounts at month end; active_players counts accounts with gaming/POS/ledger activity that month.
- Ledger timing uses gaming date derived from event_at_utc, not available_at_utc. Balances are as-of gaming-month boundaries, summing points_delta from the annual opening. Both balance snapshots cover the same enrolled cohort; newly enrolled accounts enter at zero.
- Flags indicate candidate changes only. If grouping by current/event-time tier is later requested, this requires a revised contract with explicit tier-transfer reconciliation, not relabeling these rows.
- Checks: tier measures sum to tracked monthly totals; balance_end = balance_start + earned - redeemed; balances carry forward; no use of lifetime points as redeemable points.

## 14. mart_comps_daily

- Purpose: daily tracked comp economics and rate-change diagnostics.
- Grain/key: gaming_date; all historical gaming dates.
- Sources: sessions for daily tracked gaming, ledger for redemptions/points, POS for linked receipts, players for balances. Independently aggregate to date before joining.
- Columns: gaming_date DATE; month_start DATE; group C; active_players COUNT; policy_change_candidate FLAG nullable; change_method, change_status TEXT.
- Actual loss is from sessions, not prorated from player_period. Comp cost comes from ledger redemptions, reconciled to POS economic costs. Capture any linked non-POS benefit coverage separately in diagnostics rather than assuming all benefits are receipts.
- Comp change candidates require evidence in both cost/coin-in and cost/actual-loss series and valid denominators; do not automatically label a pricing/policy cause. Test method, minimum window and thresholds remain review choices.
- Checks: daily summed economics reconcile to monthly source totals on the same activity-month basis; daily balances carry forward. Balance snapshots and active player counts are non-additive over dates.
- Stage 4 preserves policy_change_candidate=NULL with explicit configuration status. Whole-month, single-year builds are required for source player-month reconciliation. Unsupported non-POS redemption links fail validation; all supplied redemptions have verified matching POS links.

## 15. mart_forecast

- Purpose: reproducible model/baseline comparisons and a July no-action demand reference.
- Grain/key: forecast_date; one chosen method/run per published build.
- Sources: floor daily for historical target; generated calendar and eligible announced-event features.
- Columns: forecast_date DATE; split TEXT (train/validation/test/future); actual_coin_in_usd MONEY nullable (NULL in future); model_prediction_usd, baseline_prediction_usd MONEY nullable; model_method TEXT; fit_start, fit_end, forecast_origin DATE nullable; prediction_frozen_at_utc UTC nullable; evaluation_eligible FLAG; weekday_index COUNT.
- Jan-Mar training rows have NULL published evaluation predictions. April contains out-of-sample selected-candidate and baseline predictions fit on Jan-Mar. May-Jun predictions are frozen from Jan-Apr fits. July predictions are from Jan-Jun refits. Store all candidate April results separately in model diagnostics.
- Candidate selection uses April only; historical future events must have been announced by the forecast origin, not merely by the event date. Weather, later-published visitation and holdout actual-derived lags are excluded.
- Diagnostics include model/baseline MAE overall/by weekday, selection results, training ranges and feature provenance. Prediction freeze is a procedural audit record, not proof that historical files were never inspected.
- Checks: 211 default dates; actuals match floor daily; fitting windows precede evaluated dates; no refitting within May-Jun; no historical holiday/event lookup masquerading as known July data.
- Implemented candidates: weekday means versus weekday/holiday/advance-announced city/property-event regression. April MAE selects; ties prefer weekday means. Predictions are nonnegative, cent-rounded and frozen in diagnostics.forecast_frozen_predictions before evaluation. Actual build timestamps and simulated forecast origins are distinct. Future holiday inputs explicitly include July 4; event coverage is limited to supplied announcements.

## 16. mart_actions

- Purpose: reviewable proposed budget allocation, with assumptions rather than fabricated causal effects.
- Grain/key: proposal_line_id. One row per action type and explicit target; quantity can exceed one only for a homogeneous target/package with nonoverlapping units. Selected rows form one proposed portfolio per build.
- Sources: action_catalog, configured proposals, evidence marts, forecast and explicit effect assumptions.
- Columns: proposal_line_id, action_type_id, target_id ID; target_type TEXT (machine/bank/zone/manufacturer/shift/property); selected FLAG; quantity COUNT; horizon_start, horizon_end DATE; lead_days COUNT; effective_operating_days, action_downtime_hours NUMBER; unit_cost_usd, recurring_cost_per_day_usd, additional_comp_cost_usd, total_cost_usd MONEY; benefit_before_action_cost_usd, benefit_low_usd, benefit_high_usd, net_benefit_usd, half_effect_net_benefit_usd MONEY nullable; effect_assumption TEXT; evidence_refs TEXT; measurement_metric, control_definition, limitation TEXT; benefit_status TEXT.
- Operating days = max(0, horizon length - lead_days). Total cost = quantity * (unit cost + recurring daily cost * operating days) + additional comp cost, respecting catalogue package definitions. Full purchase/package costs count against budget.
- benefit_before_action_cost is incremental expected contribution after ongoing machine costs and operational downtime, BEFORE proposal costs. net_benefit subtracts total_cost once. Maintain a cost-component reconciliation to avoid double-counting lease/service expenses in both places.
- low/high are explicit assumption or validated error scenarios, not automatically 95% confidence intervals. NULL benefit is valid for inspection/information actions. Half-effect scenario = 0.5 * benefit_before_action_cost - total_cost.
- Forecast supplies a floor-level no-action reference; allocating it to a target requires an explicit allocation assumption. Forecast alone does not estimate intervention uplift.
- Checks: selected portfolio <= $100,000; working-plan action-type cap is disabled per user instruction (official submission guide: 3 types). Catalogue quantity limits apply across all selected rows; enforce incompatibilities/target conflicts; nonnegative quantities/costs; horizon is July 1-30. Empty proposals yield a valid empty mart with schema and an explicit unallocated budget report, not invented recommendations.
- Stage 7 adds benefit_days_per_unit NUMBER; affected_machine_count COUNT; nullable downtime_opportunity_cost_usd_per_hour and forecast_no_action_coin_in_usd MONEY; nullable forecast_allocation_share NUMBER; unit_start_dates/cost_assumption TEXT. Uplift scenarios are per unit/day before proposal charges, reduced for downtime and explicit duration. Active target membership, quantity/incompatibility expansion and configuration snapshots are recorded. See docs/action_proposals.md for input rules and limitations.

## 17. Validation and acceptance

Build fails on missing required sources/columns, duplicate keys, unresolved required joins, accounting identity failures, or impossible time intervals. Source-specific monetary tolerances derive from source precision; no blanket tolerance that hides material discrepancies.

Unavailable analytical estimates are allowed only with NULL values and explicit statuses. Unknown estimates never become zero benefits/losses.

Required test fixtures: partial install day; spring DST gaming day; repeated autumn UTC/local hour conversion; machine move; overlapping tickets; offline counters; zero wagers; negative house win; redemption without gaming; changing tier; visit spanning months; no comparable neighbors; source period truncation; conflicting budget actions.

Required integration checks: source manifest/schema checks; machine hour -> day -> month reconciliation; player/session/card-meter coverage; ledger/POS comp reconciliation; daily -> tier-month totals under fixed cohorts; forecast split leakage checks; complete deterministic rebuild with a fixed seed.

Performance target: SQL aggregates execute inside DuckDB. Python receives machine-day summaries and model inputs, not full joined session/POS facts. Large hourly mart is written directly from DuckDB, not assumed to be a small CSV.

## 18. Decisions for review before implementation

1. Approve fixed opening-tier cohorts for mart_comps_tier_month? It preserves reconciliation but does not directly show event-time tier policy effects.
2. Approve first-visit-month cohort attribution for mart_visits_month? This deliberately differs from activity-month wagering totals.
3. Approve adjusted rank based on expected contribution per available hour? Total expected contribution will also remain available.
4. Set evidence eligibility/thresholds: minimum active days, positive-exposure days, bootstrap usable blocks, peer coverage, weak-demand gap, downtime share and protective loss flag. Proposed starting eligibility: >= 60 active dates, >= 30 positive-wager dates and >= 8 usable seven-day blocks; thresholds are sensitivity parameters, not statistical guarantees.
5. Set downtime reference windows and hidden-downtime rule. Proposed first pass: +/- 28 dates in the same placement/configuration and local hour band, >= 3 eligible other-bank peers; >= 3 consecutive available zero-play hours with busy peers is a candidate. Busy-peer threshold and minimum healthy observations still need calibration.
6. Approve alpha = 0.05, two-sided CLT tests with BH across each declared family; seeded 10,000-replicate block intervals as sensitivity checks. Stratification/dependence diagnostics cannot be reduced to a near-zero correlation test.
7. Approve classification as overlapping evidence flags plus mixed/insufficient outcomes; no automatic replacement verdict from a p-value alone.
8. Resolved in stage 3: property contribution subtracts tech labor once; weather tmax_c/prcp_mm are Celsius/mm; Missouri handle/AGR and LVCVA visitor_volume mappings are documented in sections 6 and 9.
9. Choose/document comp change detection (window sizes, effect size and multiplicity) before creating policy-change flags. No fitted thresholds are implied by this draft.
10. Approve all 14 outputs, including machine-hour and player-level marts which will be larger than the other exports. Recommendation benefits remain configurable assumptions until supported by analysis.
