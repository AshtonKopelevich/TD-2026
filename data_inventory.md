# Dataset inventory and question map

Generated with DuckDB from Parquet schemas and file metadata; no data rows scanned or printed. CSV.gz files duplicate the Parquet tables and are excluded.

**31 tables; 3,885,259 stored rows across tables.** These are different grains and overlapping views, not distinct observations.

## Available SQL types

| SQL type | Column count |
| --- | ---: |
| BIGINT | 59 |
| BOOLEAN | 6 |
| DATE | 20 |
| DECIMAL(10,6) | 1 |
| DECIMAL(10,8) | 2 |
| DECIMAL(12,2) | 1 |
| DECIMAL(18,10) | 6 |
| DECIMAL(18,2) | 27 |
| DECIMAL(18,4) | 5 |
| DECIMAL(18,6) | 1 |
| DECIMAL(18,8) | 1 |
| DECIMAL(24,2) | 6 |
| DECIMAL(24,8) | 3 |
| DECIMAL(8,1) | 3 |
| DOUBLE | 24 |
| INTEGER | 18 |
| TIMESTAMP | 35 |
| VARCHAR | 209 |

DECIMAL preserves fixed precision (including money); BIGINT/INTEGER store counts or cents; DOUBLE stores approximate measures; VARCHAR stores labels/IDs; DATE/TIMESTAMP store time; BOOLEAN stores flags. A timestamp's `_utc`/`_local` suffix conveys its timezone convention.

## Required questions and relevant data

Question wording comes from GUIDE.md. Starter/drill-down roles follow its mapping; additional tables and column selections below are suggested analysis aids, not statistical correlations.

### Q1: Which machines are *truly* underperforming once you account for exposure, availability and luck?

Start with: `prepared_daily_view`.

Drill down/context: `machine_day`, `game_math`, `placements`, `machines`, `floor_locations`, `floor_walkways`, `calendar_day`, `cost_rules`.

Compare theo, house win and contribution per available hour; account for active days, location, RTP and volatility.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| prepared_daily_view | `machine_id` (VARCHAR), `gaming_date` (DATE), `events_active` (VARCHAR), `zone_id` (VARCHAR), `zone_name` (VARCHAR), `location_id` (VARCHAR), `config_id` (VARCHAR), `configured_rtp` (DECIMAL(10,8)), `volatility_class` (VARCHAR), `active` (BOOLEAN), `available_hours` (DOUBLE), `occupied_hours` (DOUBLE), `occupancy_ratio` (DOUBLE), `coin_in_usd` (DECIMAL(18,2)), `house_win_usd` (DECIMAL(18,2)), `theo_usd` (DECIMAL(18,4)), `theo_hold` (DOUBLE), `luck_residual_usd` (DECIMAL(18,4)), `carded_coin_in_usd` (DECIMAL(18,2)), `zone_entries_observed` (BIGINT), `zone_counter_coverage_hours` (DOUBLE), `lease_cost_usd` (DECIMAL(18,2)), `service_cost_usd` (DECIMAL(18,2)), `power_cost_usd` (DECIMAL(18,2)), `repair_cost_usd` (DECIMAL(18,2)), `contribution_after_supplied_costs_usd` (DECIMAL(18,2)), `lag_coin_in_7d_mean_usd` (DOUBLE), `lag_house_win_28d_usd` (DOUBLE) |
| machine_day | `machine_id` (VARCHAR), `gaming_date` (DATE), `location_id` (VARCHAR), `config_id` (VARCHAR), `active` (BOOLEAN), `available_seconds` (BIGINT), `occupied_seconds` (BIGINT), `coin_in_cents` (BIGINT), `house_win_cents` (BIGINT), `theo_cents` (DECIMAL(24,8)), `carded_coin_in_cents` (BIGINT), `carded_theo_cents` (DECIMAL(24,8)) |
| game_math | `config_id` (VARCHAR), `configured_rtp` (DECIMAL(10,8)), `volatility_class` (VARCHAR) |
| placements | `machine_id` (VARCHAR), `location_id` (VARCHAR), `config_id` (VARCHAR), `effective_from_utc` (TIMESTAMP), `effective_to_utc` (TIMESTAMP) |
| machines | `machine_id` (VARCHAR) |
| floor_locations | `location_id` (VARCHAR), `parent_location_id` (VARCHAR), `zone_id` (VARCHAR) |
| floor_walkways | `zone_a` (VARCHAR), `zone_b` (VARCHAR) |
| calendar_day | `gaming_date` (DATE) |
| cost_rules | `cost_rule_id` (VARCHAR), `cost_category` (VARCHAR), `effective_from` (DATE), `effective_to` (DATE) |

### Q2: What changed in demand across the floor over the six months, and why?

Start with: `property_day`, `zone_traffic_hourly`.

Drill down/context: `events`, `calendar_day`, `prepared_daily_view`, `placements`, `city_visitation_monthly`, `weather_daily`, `visitor_profile_summary`, `visitor_profile_segments`, `benchmark_public`, `benchmark_property_monthly`, `benchmark_state_monthly`, `visitor_profile_monthly`.

Compare daily/monthly demand and zone patterns with events, weather and city trends. Associations do not establish causes; public benchmarks describe other populations.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| property_day | `gaming_date` (DATE), `events_active` (VARCHAR), `coin_in_usd` (DECIMAL(18,2)), `occupied_machine_hours` (DOUBLE), `carded_coin_in_share` (DOUBLE), `entrance_zone_entries_observed` (BIGINT), `total_zone_entries_observed` (BIGINT), `counter_coverage_share` (DOUBLE) |
| zone_traffic_hourly | `zone_id` (VARCHAR), `entries_count` (BIGINT), `counter_status` (VARCHAR), `coverage_minutes` (INTEGER) |
| events | `event_id` (VARCHAR), `event_type` (VARCHAR), `start_date` (DATE), `end_date` (DATE), `announced_date` (DATE) |
| calendar_day | `gaming_date` (DATE), `month` (VARCHAR), `federal_holiday` (VARCHAR) |
| prepared_daily_view | `gaming_date` (DATE), `month` (VARCHAR), `federal_holiday` (VARCHAR), `events_active` (VARCHAR), `zone_id` (VARCHAR), `zone_name` (VARCHAR), `occupied_hours` (DOUBLE), `occupancy_ratio` (DOUBLE), `coin_in_usd` (DECIMAL(18,2)), `carded_coin_in_usd` (DECIMAL(18,2)), `zone_entries_observed` (BIGINT), `zone_counter_coverage_hours` (DOUBLE), `lag_coin_in_7d_mean_usd` (DOUBLE) |
| placements | See full schema below for contextual fields. |
| city_visitation_monthly | `month` (VARCHAR), `days_in_month` (INTEGER), `visitor_volume` (BIGINT), `mean_visitors_per_calendar_day` (DECIMAL(18,6)), `visitor_yoy_ratio` (DECIMAL(18,10)), `hotel_occupancy_ratio` (DECIMAL(18,10)) |
| weather_daily | `source_date` (DATE) |
| visitor_profile_summary | `publication_date` (DATE) |
| visitor_profile_segments | `publication_date` (DATE) |
| benchmark_public | `month` (VARCHAR), `retrieved_date` (DATE) |
| benchmark_property_monthly | `month` (VARCHAR), `retrieved_date` (DATE) |
| benchmark_state_monthly | `month` (VARCHAR), `retrieved_date` (DATE) |
| visitor_profile_monthly | `month` (VARCHAR) |

### Q3: How much play was lost to downtime, and when?

Start with: `prepared_daily_view`, `operations`, `calendar_day`.

Drill down/context: `machine_day`, `machine_hour`, `shift_roster`, `machines`.

Estimate lost play from a comparable-machine/time baseline and unavailable hours. Lost play is an estimate, not an observed column; use scheduled_seconds for DST.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| prepared_daily_view | `machine_id` (VARCHAR), `gaming_date` (DATE), `is_weekend` (BOOLEAN), `events_active` (VARCHAR), `manufacturer` (VARCHAR), `active` (BOOLEAN), `available_hours` (DOUBLE), `occupied_hours` (DOUBLE), `coin_in_usd` (DECIMAL(18,2)), `carded_coin_in_usd` (DECIMAL(18,2)), `faults_opened` (BIGINT), `zone_counter_coverage_hours` (DOUBLE), `repair_cost_usd` (DECIMAL(18,2)), `lag_coin_in_7d_mean_usd` (DOUBLE), `lag_downtime_7d_hours` (DOUBLE) |
| operations | `machine_id` (VARCHAR), `opened_at_utc` (TIMESTAMP), `opened_at_local` (TIMESTAMP), `work_started_at_utc` (TIMESTAMP), `available_at_utc` (TIMESTAMP) |
| calendar_day | `gaming_date` (DATE), `gaming_day_start_utc` (TIMESTAMP), `gaming_day_end_utc` (TIMESTAMP), `scheduled_seconds` (BIGINT), `utc_offset_start` (VARCHAR), `utc_offset_end` (VARCHAR), `is_weekend` (BOOLEAN) |
| machine_day | `machine_id` (VARCHAR), `gaming_date` (DATE), `active` (BOOLEAN), `scheduled_seconds` (BIGINT), `available_seconds` (BIGINT), `coin_in_cents` (BIGINT), `carded_coin_in_cents` (BIGINT) |
| machine_hour | `machine_id` (VARCHAR), `hour_start_utc` (TIMESTAMP), `hour_start_local` (TIMESTAMP), `local_hour` (INTEGER), `gaming_date` (DATE), `active` (BOOLEAN), `available_seconds` (BIGINT), `coin_in_cents` (BIGINT), `carded_coin_in_cents` (BIGINT) |
| shift_roster | `gaming_date` (DATE), `shift` (VARCHAR), `role` (VARCHAR), `start_utc` (TIMESTAMP), `end_utc` (TIMESTAMP) |
| machines | `machine_id` (VARCHAR), `manufacturer` (VARCHAR) |

### Q4: What did tracked players wager, get back and net, and how concentrated are those results?

Start with: `player_period`.

Drill down/context: `sessions`, `trips`, `players`, `machine_day`.

Summarize tracked wagers, payouts, player net and concentration by player/group. Player net = payout minus wagers; these tables cover carded play only.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| player_period | `player_id` (VARCHAR), `period_month` (VARCHAR), `home_region` (VARCHAR), `age_band` (VARCHAR), `opening_tier` (VARCHAR), `tier_end` (VARCHAR), `observed_visits` (BIGINT), `incomplete_visits` (BIGINT), `carded_play_hours` (DOUBLE), `tracked_coin_in_usd` (DECIMAL(18,2)), `tracked_payout_usd` (DECIMAL(18,2)), `tracked_net_usd` (DECIMAL(18,2)), `theo_usd` (DECIMAL(18,4)), `luck_residual_usd` (DECIMAL(18,4)) |
| sessions | `payout_positive_spins` (BIGINT), `coin_in_cents` (BIGINT), `payout_cents` (BIGINT), `theo_cents` (DECIMAL(24,8)), `player_id` (VARCHAR), `observed_visit_id` (VARCHAR) |
| trips | `observed_visit_id` (VARCHAR), `player_id` (VARCHAR), `observation_complete` (BOOLEAN) |
| players | `player_id` (VARCHAR), `home_region` (VARCHAR), `age_band` (VARCHAR), `opening_tier` (VARCHAR) |
| machine_day | `payout_positive_spins` (BIGINT), `coin_in_cents` (BIGINT), `payout_cents` (BIGINT), `theo_cents` (DECIMAL(24,8)), `carded_coin_in_cents` (BIGINT), `carded_payout_cents` (BIGINT), `carded_spins` (BIGINT), `carded_theo_cents` (DECIMAL(24,8)) |

### Q5: What did the loyalty (comp) program cost, and did anything about it change?

Start with: `player_period`, `property_day`.

Drill down/context: `loyalty_ledger`, `fnb_transactions`, `players`.

Track points, redemptions, economic comp cost and cost/theo over time and by tier. Comp cost is already included in linked POS COGS; do not subtract twice.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| player_period | `player_id` (VARCHAR), `period_month` (VARCHAR), `opening_tier` (VARCHAR), `tier_end` (VARCHAR), `incomplete_visits` (BIGINT), `theo_usd` (DECIMAL(18,4)), `linked_pos_cogs_usd` (DECIMAL(18,2)), `comps_redeemed` (BIGINT), `comp_face_value_usd` (DECIMAL(18,2)), `comp_cost_usd` (DECIMAL(18,2)), `points_earned` (BIGINT), `points_redeemed` (BIGINT), `tracked_contribution_usd` (DECIMAL(18,2)) |
| property_day | `gaming_date` (DATE), `events_active` (VARCHAR), `theo_usd` (DECIMAL(18,4)), `pos_cogs_usd` (DECIMAL(18,2)), `comp_face_value_usd` (DECIMAL(18,2)), `comp_cost_usd` (DECIMAL(18,2)), `machine_supplied_costs_usd` (DECIMAL(18,2)), `tech_labor_cost_usd` (DECIMAL(18,2)), `contribution_after_supplied_costs_usd` (DECIMAL(18,2)) |
| loyalty_ledger | `loyalty_event_id` (VARCHAR), `player_id` (VARCHAR), `event_at_utc` (TIMESTAMP), `event_type` (VARCHAR), `points_delta` (BIGINT), `tier_before` (VARCHAR), `tier_after` (VARCHAR), `economic_cost_cents` (BIGINT), `redeemed_pos_id` (VARCHAR) |
| fnb_transactions | `event_at_utc` (TIMESTAMP), `event_at_local` (TIMESTAMP), `player_id` (VARCHAR), `cogs_cents` (BIGINT), `comp_id` (VARCHAR) |
| players | `player_id` (VARCHAR), `opening_lifetime_points` (BIGINT), `opening_tier` (VARCHAR) |

### Q6: Which actions would you fund with **$100,000**, and how would you know they worked?

Start with: `action_catalog`, `cost_rules`.

Drill down/context: `prepared_daily_view`, `property_day`, `operations`, `placements`, `game_math`, `player_period`, `loyalty_ledger`, `fnb_transactions`, `zone_traffic_hourly`, `shift_roster`.

Recommend up to 3 action types within $100,000 for July 1-30, 2025. Price quantities, lead times, recurring costs and incompatibilities; give expected effects, uncertainty and a measurement/control plan. Keeping the budget is valid; catalogue prices do not imply benefits.

| Table | Relevant columns (actual SQL types) |
| --- | --- |
| action_catalog | `action_type_id` (VARCHAR), `unit` (VARCHAR), `unit_cost_cents` (BIGINT), `recurring_cost_cents_per_day` (BIGINT), `lead_days` (INTEGER), `downtime_minutes` (INTEGER), `quantity_limit` (INTEGER), `incompatibility_group` (VARCHAR) |
| cost_rules | `cost_rule_id` (VARCHAR), `cost_category` (VARCHAR), `unit` (VARCHAR) |
| prepared_daily_view | `available_hours` (DOUBLE), `theo_usd` (DECIMAL(18,4)), `theo_hold` (DOUBLE), `lease_cost_usd` (DECIMAL(18,2)), `service_cost_usd` (DECIMAL(18,2)), `power_cost_usd` (DECIMAL(18,2)), `repair_cost_usd` (DECIMAL(18,2)), `contribution_after_supplied_costs_usd` (DECIMAL(18,2)), `lag_downtime_7d_hours` (DOUBLE) |
| property_day | `theo_usd` (DECIMAL(18,4)), `available_machine_hours` (DOUBLE), `comp_cost_usd` (DECIMAL(18,2)), `machine_supplied_costs_usd` (DECIMAL(18,2)), `tech_labor_cost_usd` (DECIMAL(18,2)), `contribution_after_supplied_costs_usd` (DECIMAL(18,2)) |
| operations | `available_at_utc` (TIMESTAMP), `direct_cost_cents` (BIGINT) |
| placements | See full schema below for contextual fields. |
| game_math | See full schema below for contextual fields. |
| player_period | `theo_usd` (DECIMAL(18,4)), `comp_cost_usd` (DECIMAL(18,2)), `tracked_contribution_usd` (DECIMAL(18,2)) |
| loyalty_ledger | `available_at_utc` (TIMESTAMP), `economic_cost_cents` (BIGINT) |
| fnb_transactions | `transaction_id` (VARCHAR) |
| zone_traffic_hourly | See full schema below for contextual fields. |
| shift_roster | See full schema below for contextual fields. |

## Additional requirements and analysis cautions

- Include one useful ML/time-series method with a simple baseline and time-based holdout. Suggested route: forecast property_day coin-in using calendar_day weekday; train January-April, evaluate May-June with MAE. Avoid future information.
- Dashboard: allow period changes and bank/guest-group drill-down; show model validation and trace each recommendation to evidence.
- Deliver a public interactive dashboard, <=2-minute video, <=400-word write-up, code, Claims & Evidence appendix and AI-use disclosure (GUIDE.md sections 7-8).
- Aggregate separate fact tables to a shared grain before joining; joining sessions and receipts row-by-row multiplies money.
- Placements require interval joins: effective_from_utc <= timestamp < effective_to_utc; use prepared_daily_view for already-resolved machine-day location.
- Exclude inactive machine-days from performance comparisons; missing traffic counts are not zero and entries are not unique people.
- Compute ratios from sums. Preserve cents versus dollars, house versus player net signs, and carded versus all-play coverage.
- Source dataset is fictional/synthetic except separate real_sources files; January-June 2025; gaming days start 06:00 America/Los_Angeles. Release is a draft.

## Full table and column inventory

### player_period

File: `data/1_prepared_views/player_period.parquet`; metadata rows: **148,893**.

Starter table: tracked results per player per month. Tracked only; uncarded play is invisible.
Rows: 148,893 · Key: `player_id, period_month`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `player_id` | VARCHAR | Loyalty account (opaque) |
| `period_month` | VARCHAR | YYYY-MM by gaming date |
| `home_region` | VARCHAR | Coarse home region |
| `age_band` | VARCHAR | Coarse age band |
| `opening_tier` | VARCHAR | Tier at the start of the window |
| `tier_end` | VARCHAR | Tier after the last ledger event so far |
| `observed_visits` | BIGINT | Recorded property visits |
| `incomplete_visits` | BIGINT | Visits still open at window end |
| `sessions` | BIGINT | Distinct logical sessions |
| `carded_play_hours` | DOUBLE | Hours of carded play |
| `tracked_coin_in_usd` | DECIMAL(18,2) | Coin-in on carded play, dollars |
| `tracked_payout_usd` | DECIMAL(18,2) | Payout on carded play, dollars |
| `tracked_net_usd` | DECIMAL(18,2) | Player view: payout - coin-in |
| `theo_usd` | DECIMAL(18,4) | Theoretical win: wager x (1 - configured RTP), dollars |
| `luck_residual_usd` | DECIMAL(18,4) | tracked net + theo |
| `linked_pos_cash_usd` | DECIMAL(18,2) | POS cash linked to the player card, dollars |
| `linked_pos_cogs_usd` | DECIMAL(18,2) | Includes comp costs |
| `comps_redeemed` | BIGINT | Comps redeemed |
| `comp_face_value_usd` | DECIMAL(18,2) | Menu value of comped items, dollars (not cash revenue) |
| `comp_cost_usd` | DECIMAL(18,2) | Already inside linked_pos_cogs_usd; do not subtract twice |
| `points_earned` | BIGINT | Loyalty points awarded |
| `points_redeemed` | BIGINT | Loyalty points spent |
| `tracked_contribution_usd` | DECIMAL(18,2) | coin-in - payout + POS cash - POS cogs |

### prepared_daily_view

File: `data/1_prepared_views/prepared_daily_view.parquet`; metadata rows: **56,110**.

Starter table: one row per machine-day with history, costs and context already joined, in dollars.
Rows: 56,110 · Key: `machine_id, gaming_date`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `machine_id` | VARCHAR | Machine key |
| `gaming_date` | DATE | Gaming day: 06:00 local to 06:00 next day |
| `month` | VARCHAR | Calendar or gaming month, YYYY-MM |
| `local_weekday` | VARCHAR | Weekday of the gaming date |
| `is_weekend` | BOOLEAN | Saturday or Sunday |
| `federal_holiday` | VARCHAR | US federal holiday name, if any |
| `events_active` | VARCHAR | Event names active that gaming date |
| `zone_id` | VARCHAR | Zone key (floor_locations) |
| `zone_name` | VARCHAR | Readable zone name |
| `bank_id` | VARCHAR | Bank key |
| `location_id` | VARCHAR | Slot position key (floor_locations) |
| `config_id` | VARCHAR | Game configuration key (game_math) |
| `theme` | VARCHAR | Fictional game title |
| `configured_rtp` | DECIMAL(10,8) | Configured return to player (long-run) |
| `volatility_class` | VARCHAR | Payout dispersion class: low / medium / high / very_high |
| `manufacturer` | VARCHAR | Fictional manufacturer |
| `lease_class` | VARCHAR | owned / leased_fixed / leased_revenue_share |
| `active` | BOOLEAN | Installed and on the floor that day |
| `meter_status` | VARCHAR | reported / not_installed / retired |
| `available_hours` | DOUBLE | Hours available (not down) |
| `occupied_hours` | DOUBLE | Hours with a player seated |
| `availability_ratio` | DOUBLE | available / scheduled |
| `occupancy_ratio` | DOUBLE | occupied / available |
| `paid_spins` | BIGINT | Number of paid spins |
| `coin_in_usd` | DECIMAL(18,2) | Total wagered, dollars, including replayed winnings |
| `payout_usd` | DECIMAL(18,2) | Amount paid back to players, dollars |
| `house_win_usd` | DECIMAL(18,2) | Coin-in minus payout, dollars (can be negative) |
| `theo_usd` | DECIMAL(18,4) | Theoretical win: wager x (1 - configured RTP), dollars |
| `observed_hold` | DOUBLE | house win / coin-in; null without play |
| `theo_hold` | DOUBLE | theo / coin-in |
| `luck_residual_usd` | DECIMAL(18,4) | house win - theo |
| `carded_coin_in_usd` | DECIMAL(18,2) | Coin-in on carded play, dollars |
| `carded_share` | DOUBLE | carded / all coin-in |
| `faults_opened` | BIGINT | fault_repair tickets opened that day |
| `zone_entries_observed` | BIGINT | Counter entries for the zone that day (observed) |
| `zone_counter_coverage_hours` | DOUBLE | Counter coverage that day |
| `lease_cost_usd` | DECIMAL(18,2) | Lease cost from cost_rules, dollars |
| `service_cost_usd` | DECIMAL(18,2) | Manufacturer service contract cost, dollars |
| `power_cost_usd` | DECIMAL(18,2) | Utilities cost, dollars |
| `repair_cost_usd` | DECIMAL(18,2) | Direct repair cost, dollars |
| `contribution_after_supplied_costs_usd` | DECIMAL(18,2) | house win minus the supplied machine costs above |
| `lag_coin_in_7d_mean_usd` | DOUBLE | Mean of the previous 7 gaming days (model-safe) |
| `lag_downtime_7d_hours` | DOUBLE | Downtime over the previous 7 gaming days (model-safe) |
| `lag_house_win_28d_usd` | DOUBLE | House win over the previous 28 gaming days (model-safe) |

### property_day

File: `data/1_prepared_views/property_day.parquet`; metadata rows: **181**.

Starter table: one row per gaming day for the whole property.
Rows: 181 · Key: `gaming_date`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `gaming_date` | DATE | Gaming day: 06:00 local to 06:00 next day |
| `local_weekday` | VARCHAR | Weekday of the gaming date |
| `events_active` | VARCHAR | Events from the events table active that day |
| `active_machines` | BIGINT | Machines installed that day |
| `coin_in_usd` | DECIMAL(18,2) | Total wagered, dollars, including replayed winnings |
| `payout_usd` | DECIMAL(18,2) | Amount paid back to players, dollars |
| `house_win_usd` | DECIMAL(18,2) | Coin-in minus payout, dollars (can be negative) |
| `theo_usd` | DECIMAL(18,4) | Theoretical win: wager x (1 - configured RTP), dollars |
| `observed_hold` | DOUBLE | House win / coin-in (null when no coin-in) |
| `available_machine_hours` | DOUBLE | Machine-hours available (not down/closed) |
| `occupied_machine_hours` | DOUBLE | Machine-hours with a player seated |
| `carded_coin_in_share` | DOUBLE | Carded coin-in / all coin-in |
| `pos_cash_usd` | DECIMAL(18,2) | POS cash received, dollars |
| `pos_cogs_usd` | DECIMAL(18,2) | POS cost of goods incl. comped items, dollars |
| `comp_face_value_usd` | DECIMAL(18,2) | Menu value of comped items, dollars (not cash revenue) |
| `comp_cost_usd` | DECIMAL(18,2) | Inside pos_cogs_usd |
| `faults_opened` | BIGINT | Fault tickets opened |
| `incidents_reported` | BIGINT | Security incidents reported that day |
| `entrance_zone_entries_observed` | BIGINT | Entries in zones with doors |
| `total_zone_entries_observed` | BIGINT | Sum of all zone counter entries (crossings, not unique people) |
| `counter_coverage_share` | DOUBLE | Share of sensor-minutes with a working counter |
| `machine_supplied_costs_usd` | DECIMAL(18,2) | Lease, service, power and repair |
| `tech_labor_cost_usd` | DECIMAL(18,2) | Scheduled slot-technician labour cost, dollars |
| `contribution_after_supplied_costs_usd` | DECIMAL(18,2) | house win + POS cash - POS cogs - supplied costs |

### action_catalog

File: `data/2_machine_decision/action_catalog.parquet`; metadata rows: **13**.

What the $100,000 / 30-day budget can buy. No uplift is promised.
Rows: 13 · Key: `action_type_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `action_type_id` | VARCHAR | Action |
| `name` | VARCHAR | Description |
| `unit` | VARCHAR | Unit of quantity |
| `unit_cost_cents` | BIGINT | One-time cost per unit |
| `recurring_cost_cents_per_day` | BIGINT | Per unit per day |
| `lead_days` | INTEGER | Days before it takes effect |
| `downtime_minutes` | INTEGER | Machine downtime per unit |
| `quantity_limit` | INTEGER | Max units |
| `incompatibility_group` | VARCHAR | Actions in one group conflict on the same target |
| `notes` | VARCHAR | Constraints |

### calendar_day

File: `data/2_machine_decision/calendar_day.parquet`; metadata rows: **181**.

One row per gaming day.
Rows: 181 · Key: `gaming_date`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `gaming_date` | DATE | Gaming day: 06:00 local to 06:00 next day |
| `gaming_day_start_utc` | TIMESTAMP | Start instant, UTC |
| `gaming_day_end_utc` | TIMESTAMP | End instant, UTC (exclusive) |
| `scheduled_seconds` | BIGINT | Elapsed seconds; 82800 on the spring DST gaming day |
| `local_weekday` | VARCHAR | Weekday of the gaming date |
| `utc_offset_start` | VARCHAR | UTC offset at start |
| `utc_offset_end` | VARCHAR | UTC offset at end |
| `month` | VARCHAR | YYYY-MM |
| `is_weekend` | BOOLEAN | Saturday or Sunday |
| `federal_holiday` | VARCHAR | US federal holiday name, if any |

### cost_rules

File: `data/2_machine_decision/cost_rules.parquet`; metadata rows: **9**.

Supplied costs. Subtract each once.
Rows: 9 · Key: `cost_rule_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `cost_rule_id` | VARCHAR | Rule |
| `entity_type` | VARCHAR | What it applies to |
| `entity_id` | VARCHAR | Which one; blank = all |
| `cost_category` | VARCHAR | lease \| service_contract \| utilities \| labor \| repair \| cost_of_goods |
| `calculation_basis` | VARCHAR | How to apply the rate |
| `unit` | VARCHAR | cents \| fraction \| multiplier |
| `payer` | VARCHAR | property |
| `rate` | VARCHAR | Rate in the stated unit |
| `effective_from` | DATE | Start |
| `effective_to` | DATE | End; null = open |

### floor_locations

File: `data/2_machine_decision/floor_locations.parquet`; metadata rows: **378**.

Floor hierarchy and coordinates. Walkways are in floor_walkways.
Rows: 378 · Key: `location_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `location_id` | VARCHAR | Zone, bank, slot, outlet or entrance key |
| `parent_location_id` | VARCHAR | Parent node |
| `node_type` | VARCHAR | zone \| bank \| slot \| outlet \| entrance |
| `zone_id` | VARCHAR | Zone |
| `bank_id` | VARCHAR | Bank |
| `outlet_id` | VARCHAR | Outlet |
| `name` | VARCHAR | Display name |
| `x_m` | DOUBLE | Floor x, metres |
| `y_m` | DOUBLE | Floor y, metres |
| `capacity` | INTEGER | Machine positions or seats |

### floor_walkways

File: `data/2_machine_decision/floor_walkways.parquet`; metadata rows: **10**.

Walkable edges between zone hubs, with the effective-dated renovation closure.
Rows: 10 · Key: `walkway_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `walkway_id` | VARCHAR | Walkway key |
| `zone_a` | VARCHAR | Zone at one end (floor_locations.zone_id) |
| `zone_b` | VARCHAR | Zone at the other end |
| `length_m` | DOUBLE | Walking length in metres |
| `closed_from_utc` | TIMESTAMP | Start of closure (inclusive), UTC; null if never closed |
| `closed_to_utc` | TIMESTAMP | End of closure (exclusive), UTC |
| `closure_reason` | VARCHAR | Why the walkway was closed |

### game_math

File: `data/2_machine_decision/game_math.parquet`; metadata rows: **10**.

Rows: 10 · Key: `config_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `config_id` | VARCHAR | Published game configuration |
| `theme` | VARCHAR | Game title |
| `configured_rtp` | DECIMAL(10,8) | Long-run expected return per unit wagered |
| `payout_multiplier_variance` | DECIMAL(18,8) | Variance of payout/bet per spin |
| `hit_probability` | DECIMAL(10,6) | Probability a spin pays more than zero (may be less than the bet) |
| `max_multiplier` | DECIMAL(12,2) | Largest fixed award as a multiple of the bet |
| `min_bet_cents` | BIGINT | Smallest bet |
| `max_bet_cents` | BIGINT | Largest bet |
| `bet_options_cents` | VARCHAR | Allowed fixed bets, pipe separated |
| `payout_increment_cents` | INTEGER | All payouts are multiples of this |
| `volatility_class` | VARCHAR | Qualitative |

### machine_day

File: `data/2_machine_decision/machine_day.parquet`; metadata rows: **56,110**.

Every machine x every gaming day, including zero-play and not-yet-installed days.
Rows: 56,110 · Key: `machine_id, gaming_date`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `machine_id` | VARCHAR | Machine |
| `gaming_date` | DATE | Gaming day |
| `location_id` | VARCHAR | Placement at day start |
| `config_id` | VARCHAR | Configuration |
| `active` | BOOLEAN | On the floor for any part of the day |
| `meter_status` | VARCHAR | reported \| not_installed \| retired |
| `scheduled_seconds` | BIGINT | Seconds on the floor during the day |
| `available_seconds` | BIGINT | Scheduled minus outage, repair, move and install downtime |
| `occupied_seconds` | BIGINT | Seconds inside play segments |
| `paid_spins` | BIGINT | All play |
| `payout_positive_spins` | BIGINT | Spins with payout > 0 |
| `coin_in_cents` | BIGINT | All wagers incl. replayed winnings |
| `payout_cents` | BIGINT | All game payouts |
| `house_win_cents` | BIGINT | coin_in - payout; may be negative |
| `theo_cents` | DECIMAL(24,8) | Sum of bet x (1 - configured_rtp) |
| `sum_bet_squared` | DOUBLE | Sum of bet^2 (cents^2) |
| `carded_coin_in_cents` | BIGINT | Subset recorded to a loyalty card |
| `carded_payout_cents` | BIGINT | Carded subset |
| `carded_spins` | BIGINT | Carded subset |
| `carded_theo_cents` | DECIMAL(24,8) | Carded subset |

### machines

File: `data/2_machine_decision/machines.parquet`; metadata rows: **310**.

Rows: 310 · Key: `machine_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `machine_id` | VARCHAR | Machine key; carries no location or performance meaning |
| `manufacturer` | VARCHAR | Fictional |
| `theme` | VARCHAR | Game title |
| `install_date` | DATE | Install date |
| `retire_date` | DATE | Removal date, if any |
| `lease_class` | VARCHAR | owned \| leased_fixed \| leased_revenue_share |

### operations

File: `data/2_machine_decision/operations.parquet`; metadata rows: **1,226**.

Rows: 1,226 · Key: `operation_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `operation_id` | VARCHAR | Ticket |
| `machine_id` | VARCHAR | Machine |
| `location_id` | VARCHAR | Location (destination for a move) |
| `event_type` | VARCHAR | fault_repair \| scheduled_maintenance \| move \| install \| retire |
| `opened_at_utc` | TIMESTAMP | Machine became unavailable |
| `opened_at_local` | TIMESTAMP | Same, local clock |
| `recorded_at_utc` | TIMESTAMP | Ticket entered |
| `work_started_at_utc` | TIMESTAMP | Technician started work |
| `available_at_utc` | TIMESTAMP | Available again |
| `direct_cost_cents` | BIGINT | Supplied direct cost |

### placements

File: `data/2_machine_decision/placements.parquet`; metadata rows: **314**.

Rows: 314 · Key: `placement_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `placement_id` | VARCHAR | Interval key |
| `machine_id` | VARCHAR | Machine |
| `location_id` | VARCHAR | Slot |
| `config_id` | VARCHAR | Configuration |
| `effective_from_utc` | TIMESTAMP | Start (inclusive), a gaming-day boundary |
| `effective_to_utc` | TIMESTAMP | End (exclusive); null = still placed |

### fnb_transactions

File: `data/3_guests/fnb_transactions.parquet`; metadata rows: **227,833**.

All POS tickets, carded or not.
Rows: 227,833 · Key: `transaction_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `transaction_id` | VARCHAR | POS ticket |
| `outlet_id` | VARCHAR | Outlet |
| `event_at_utc` | TIMESTAMP | Sale |
| `event_at_local` | TIMESTAMP | Sale, local clock |
| `local_hour` | INTEGER | Local clock hour (America/Los_Angeles) of the start time |
| `utc_offset` | VARCHAR | Local UTC offset at that instant, e.g. -08:00 or -07:00 |
| `recorded_at_utc` | TIMESTAMP | Ticket close |
| `player_id` | VARCHAR | Card presented |
| `observed_visit_id` | VARCHAR | Recorded visit, if carded |
| `item` | VARCHAR | Item |
| `face_value_cents` | BIGINT | Menu price |
| `cash_receipt_cents` | BIGINT | Cash; 0 for comps |
| `cogs_cents` | BIGINT | Cost of goods |
| `comp_id` | VARCHAR | Redemption that paid for it |

### loyalty_ledger

File: `data/3_guests/loyalty_ledger.parquet`; metadata rows: **782,773**.

Rows: 782,773 · Key: `loyalty_event_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `loyalty_event_id` | VARCHAR | Event |
| `player_id` | VARCHAR | Card |
| `event_at_utc` | TIMESTAMP | When |
| `available_at_utc` | TIMESTAMP | When the system knew |
| `event_type` | VARCHAR | award \| redeem |
| `benefit_id` | VARCHAR | Redeemed benefit |
| `points_delta` | BIGINT | Points change (balance starts at 0 each year) |
| `tier_before` | VARCHAR | Tier before |
| `tier_after` | VARCHAR | Tier after (tiers use lifetime points) |
| `face_value_cents` | BIGINT | Menu price (not revenue) |
| `economic_cost_cents` | BIGINT | Cost to the house; equals the linked POS cogs, count once |
| `redeemed_pos_id` | VARCHAR | Linked fnb transaction |
| `source_segment_id` | VARCHAR | Segment that earned an award |

### players

File: `data/3_guests/players.parquet`; metadata rows: **113,890**.

Rows: 113,890 · Key: `player_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `player_id` | VARCHAR | Random loyalty identity |
| `enrolled_at_utc` | TIMESTAMP | Enrollment |
| `home_region` | VARCHAR | Coarse region |
| `age_band` | VARCHAR | Coarse band; missing for some |
| `opening_lifetime_points` | BIGINT | Lifetime points on 2025-01-01 (0 if new) |
| `opening_tier` | VARCHAR | Tier on 2025-01-01 |
| `observed_through_utc` | TIMESTAMP | End of recording window |

### sessions

File: `data/3_guests/sessions.parquet`; metadata rows: **776,297**.

Carded play only.
Rows: 776,297 · Key: `session_segment_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `session_segment_id` | VARCHAR | Carded play segment |
| `logical_session_id` | VARCHAR | Physical session; split at 06:00 |
| `machine_id` | VARCHAR | Machine |
| `config_id` | VARCHAR | Configuration |
| `location_id` | VARCHAR | Location |
| `gaming_date` | DATE | Gaming day |
| `start_utc` | TIMESTAMP | First spin start |
| `end_utc` | TIMESTAMP | Last spin end |
| `start_local` | TIMESTAMP | First spin start, local clock |
| `local_hour` | INTEGER | Local clock hour (America/Los_Angeles) of the start time |
| `utc_offset` | VARCHAR | Local UTC offset at that instant, e.g. -08:00 or -07:00 |
| `fixed_bet_cents` | BIGINT | Bet on every spin |
| `paid_spins` | BIGINT | Spins |
| `payout_positive_spins` | BIGINT | Spins with payout > 0 |
| `coin_in_cents` | BIGINT | Wagers |
| `payout_cents` | BIGINT | Game payouts |
| `theo_cents` | DECIMAL(24,8) | Expected house win |
| `sum_bet_squared` | DOUBLE | Sum of bet^2 |
| `player_id` | VARCHAR | Card used |
| `observed_visit_id` | VARCHAR | Recorded visit |

### trips

File: `data/3_guests/trips.parquet`; metadata rows: **351,729**.

Rows: 351,729 · Key: `observed_visit_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `observed_visit_id` | VARCHAR | Recorded property visit (not a whole Las Vegas trip) |
| `player_id` | VARCHAR | Card |
| `first_observed_at_utc` | TIMESTAMP | First carded activity |
| `first_observed_local` | TIMESTAMP | Same, local clock |
| `last_observed_at_utc` | TIMESTAMP | Last carded activity (not a confirmed departure) |
| `grouping_method` | VARCHAR | recorded_visit_key |
| `observation_complete` | BOOLEAN | False if still open at window end |
| `observed_through_utc` | TIMESTAMP | End of recording window |

### events

File: `data/4_context/events.parquet`; metadata rows: **8**.

Calendar events; real dates verified, property promotions fictional.
Rows: 8 · Key: `event_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `event_id` | VARCHAR | Event |
| `name` | VARCHAR | Name |
| `event_type` | VARCHAR | convention \| sports_viewing \| festival \| property_promotion |
| `start_date` | DATE | First local date |
| `end_date` | DATE | Last local date |
| `announced_date` | DATE | When it was known |
| `source_type` | VARCHAR | organizer_listing \| public_calendar \| fictional_property |
| `source_url` | VARCHAR | Where dates were checked |
| `local_scope` | VARCHAR | citywide \| property |

### benchmark_property_monthly

File: `data/4_context/real_sources/benchmark_property_monthly.parquet`; metadata rows: **78**.

**Real data, unmodified.** Missouri published property slot totals (do not add to benchmark_public).
Rows: 78

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `month` | VARCHAR | Calendar or gaming month, YYYY-MM |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sheet` | VARCHAR | Original workbook sheet |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `retrieved_date` | DATE | Date the source file was downloaded |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `property_id` | VARCHAR | Stable casino key |
| `property_name_as_reported` | VARCHAR | Casino name exactly as in the source |
| `slot_units` | BIGINT | Reported number of slot machines |
| `handle_usd` | DECIMAL(24,2) | Reported slot handle (amount wagered), dollars |
| `agr_usd` | DECIMAL(24,2) | Reported adjusted gross receipts (house win), dollars |
| `actual_payout_ratio` | DECIMAL(18,10) | Reported actual payout share of handle |
| `derived_hold_ratio` | DECIMAL(18,10) | AGR / handle, computed from reported totals; null when handle missing |
| `source_cells` | VARCHAR | Sheet/cell references of the original values |

### benchmark_public

File: `data/4_context/real_sources/benchmark_public.parquet`; metadata rows: **700**.

**Real data, unmodified.** Missouri Gaming Commission slot detail, property x category x month, Jan-Jun 2025, all 13 casinos.
Rows: 700

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `month` | VARCHAR | Calendar or gaming month, YYYY-MM |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sheet` | VARCHAR | Original workbook sheet |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `retrieved_date` | DATE | Date the source file was downloaded |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `property_id` | VARCHAR | Stable casino key |
| `property_name_as_reported` | VARCHAR | Casino name exactly as in the source |
| `category` | VARCHAR | Reported slot category (denomination group) |
| `category_kind` | VARCHAR | category or adjustment row |
| `slot_units` | BIGINT | Reported number of slot machines |
| `handle_usd` | DECIMAL(24,2) | Reported slot handle (amount wagered), dollars |
| `agr_usd` | DECIMAL(24,2) | Reported adjusted gross receipts (house win), dollars |
| `actual_payout_ratio` | DECIMAL(18,10) | Reported actual payout share of handle |
| `derived_hold_ratio` | DECIMAL(18,10) | AGR / handle, computed from reported totals; null when handle missing |
| `source_cells` | VARCHAR | Sheet/cell references of the original values |

### benchmark_state_monthly

File: `data/4_context/real_sources/benchmark_state_monthly.parquet`; metadata rows: **6**.

**Real data, unmodified.** Missouri published statewide slot totals.
Rows: 6

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `month` | VARCHAR | Calendar or gaming month, YYYY-MM |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sheet` | VARCHAR | Original workbook sheet |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `retrieved_date` | DATE | Date the source file was downloaded |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `slot_units` | BIGINT | Reported number of slot machines |
| `handle_usd` | DECIMAL(24,2) | Reported slot handle (amount wagered), dollars |
| `agr_usd` | DECIMAL(24,2) | Reported adjusted gross receipts (house win), dollars |
| `source_cells` | VARCHAR | Sheet/cell references of the original values |

### city_visitation_monthly

File: `data/4_context/real_sources/city_visitation_monthly.parquet`; metadata rows: **6**.

**Real data, unmodified.** LVCVA 2025 tourism indicators (Aug 20, 2026 revision): visitors, convention attendance, hotel occupancy, airport passengers.
Rows: 6

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `month` | VARCHAR | Calendar or gaming month, YYYY-MM |
| `geography` | VARCHAR | Area the figure covers |
| `days_in_month` | INTEGER | Calendar days in month |
| `visitor_volume` | BIGINT | Las Vegas visitors in the month |
| `mean_visitors_per_calendar_day` | DECIMAL(18,6) | visitor_volume / days in month |
| `visitor_yoy_ratio` | DECIMAL(18,10) | Reported change vs same month of prior year |
| `convention_attendance` | BIGINT | Las Vegas convention attendance in the month |
| `hotel_occupancy_ratio` | DECIMAL(18,10) | Las Vegas hotel occupancy |
| `airport_en_deplaned_passengers` | BIGINT | Harry Reid airport passenger movements (not unique visitors) |
| `source_revision` | VARCHAR | Publisher revision date |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `source_cells` | VARCHAR | Sheet/cell references of the original values |
| `as_of_limitation` | VARCHAR | Why the value may not have been known at the time |

### visitor_profile_segments

File: `data/4_context/real_sources/visitor_profile_segments.parquet`; metadata rows: **1,406**.

**Real data, unmodified.** LVCVA 2025 Visitor Profile matrix, metric x segment column. Segments overlap.
Rows: 1,406

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `source_year` | INTEGER | Survey year |
| `metric_id` | VARCHAR | Stable metric key |
| `section` | VARCHAR | Report section |
| `metric_label` | VARCHAR | Metric wording as published |
| `segment_group` | VARCHAR | Segment family (segments overlap across groups) |
| `segment` | VARCHAR | Segment column label |
| `value` | VARCHAR | Reported value as published (string keeps source precision) |
| `unit` | VARCHAR | Unit of value |
| `denominator_note` | VARCHAR | Population the value is conditioned on |
| `value_status` | VARCHAR | Whether the value is reported, not applicable, etc. |
| `source_cell` | VARCHAR | Sheet/cell reference of the original value |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `publication_date` | DATE | Date the source was published |
| `limitation` | VARCHAR | Known caveat for this value |

### visitor_profile_summary

File: `data/4_context/real_sources/visitor_profile_summary.parquet`; metadata rows: **74**.

**Real data, unmodified.** LVCVA 2025 Visitor Profile, overall metrics with conditioning population and source cell.
Rows: 74

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `source_year` | INTEGER | Survey year |
| `metric_id` | VARCHAR | Stable metric key |
| `section` | VARCHAR | Report section |
| `metric_label` | VARCHAR | Metric wording as published |
| `segment_group` | VARCHAR | Segment family (segments overlap across groups) |
| `segment` | VARCHAR | Segment column label |
| `value` | VARCHAR | Reported value as published (string keeps source precision) |
| `unit` | VARCHAR | Unit of value |
| `denominator_note` | VARCHAR | Population the value is conditioned on |
| `value_status` | VARCHAR | Whether the value is reported, not applicable, etc. |
| `source_cell` | VARCHAR | Sheet/cell reference of the original value |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `publication_date` | DATE | Date the source was published |
| `limitation` | VARCHAR | Known caveat for this value |

### weather_daily

File: `data/4_context/real_sources/weather_daily.parquet`; metadata rows: **181**.

**Real data, unmodified.** NOAA GHCN-Daily, station USW00023169 (Las Vegas airport), daily TMAX/TMIN/PRCP with source flags. Calendar dates, not gaming dates.
Rows: 181

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `station_id` | VARCHAR | NOAA station |
| `source_date` | DATE | Calendar date of the observation |
| `tmax_c` | DECIMAL(8,1) | Daily maximum temperature, deg C |
| `tmax_mflag` | VARCHAR | NOAA measurement flag |
| `tmax_qflag` | VARCHAR | NOAA quality flag |
| `tmax_sflag` | VARCHAR | NOAA source flag |
| `tmax_observation_time` | VARCHAR | NOAA observation time |
| `tmin_c` | DECIMAL(8,1) | Daily minimum temperature, deg C |
| `tmin_mflag` | VARCHAR | NOAA measurement flag |
| `tmin_qflag` | VARCHAR | NOAA quality flag |
| `tmin_sflag` | VARCHAR | NOAA source flag |
| `tmin_observation_time` | VARCHAR | NOAA observation time |
| `prcp_mm` | DECIMAL(8,1) | Daily precipitation, mm |
| `prcp_mflag` | VARCHAR | NOAA measurement flag (T = trace) |
| `prcp_qflag` | VARCHAR | NOAA quality flag |
| `prcp_sflag` | VARCHAR | NOAA source flag |
| `prcp_observation_time` | VARCHAR | NOAA observation time |
| `observation_period` | VARCHAR | NOAA observation period |
| `source_revision` | VARCHAR | Publisher revision date |
| `source_id` | VARCHAR | Original file name in the provenance register |
| `source_url` | VARCHAR | Where the original file was downloaded |
| `source_sha256` | VARCHAR | SHA-256 of the original downloaded file |
| `as_of_limitation` | VARCHAR | Why the value may not have been known at the time |

### zone_traffic_hourly

File: `data/4_context/zone_traffic_hourly.parquet`; metadata rows: **30,401**.

Noisy door/zone counters. Seated players do not cross sensors.
Rows: 30,401 · Key: `sensor_id, hour_start_utc`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `sensor_id` | VARCHAR | Counter |
| `zone_id` | VARCHAR | Zone |
| `hour_start_utc` | TIMESTAMP | Hour start |
| `hour_start_local` | TIMESTAMP | Hour start, local clock |
| `local_hour` | INTEGER | Local clock hour (America/Los_Angeles) of the start time |
| `utc_offset` | VARCHAR | Local UTC offset at that instant, e.g. -08:00 or -07:00 |
| `entries_count` | BIGINT | Zone entries counted; null when offline. Not unique visitors |
| `counter_status` | VARCHAR | ok \| partial \| offline |
| `coverage_minutes` | INTEGER | Minutes the counter was working |
| `recorded_at_utc` | TIMESTAMP | Feed arrival |

### machine_hour

File: `data/5_optional/machine_hour.parquet`; metadata rows: **1,321,908**.

Every machine x every hour while installed. Sums to machine_day.
Rows: 1,321,908 · Key: `machine_id, hour_start_utc`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `machine_id` | VARCHAR | Machine |
| `hour_start_utc` | TIMESTAMP | Hour start |
| `hour_start_local` | TIMESTAMP | Local clock |
| `local_hour` | INTEGER | Local clock hour (America/Los_Angeles) of the start time |
| `utc_offset` | VARCHAR | Local UTC offset at that instant, e.g. -08:00 or -07:00 |
| `gaming_date` | DATE | Gaming day |
| `location_id` | VARCHAR | Location |
| `active` | BOOLEAN | On the floor in this hour |
| `available_seconds` | BIGINT | Available seconds in the hour |
| `occupied_seconds` | BIGINT | Seconds inside play segments |
| `paid_spins` | BIGINT | Spins started in the hour |
| `payout_positive_spins` | BIGINT | Spins with payout > 0 |
| `coin_in_cents` | BIGINT | Wagers |
| `payout_cents` | BIGINT | Payouts |
| `carded_coin_in_cents` | BIGINT | Carded subset |
| `carded_payout_cents` | BIGINT | Carded subset |
| `carded_spins` | BIGINT | Carded subset |

### security_incidents

File: `data/5_optional/security_incidents.parquet`; metadata rows: **3,865**.

Reported incidents only. Unreported events are not here. Reports are leads, not verdicts.
Rows: 3,865 · Key: `incident_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `incident_id` | VARCHAR | Report |
| `zone_id` | VARCHAR | Zone |
| `machine_id` | VARCHAR | Machine, if one was involved |
| `occurred_at_utc` | TIMESTAMP | Estimated occurrence |
| `occurred_at_local` | TIMESTAMP | Local clock |
| `local_hour` | INTEGER | Local clock hour (America/Los_Angeles) of the start time |
| `utc_offset` | VARCHAR | Local UTC offset at that instant, e.g. -08:00 or -07:00 |
| `reported_at_utc` | TIMESTAMP | Report time |
| `report_source` | VARCHAR | surveillance \| floor_staff \| slot_tech \| patron |
| `category` | VARCHAR | Reported category; not a finding of wrongdoing |
| `severity` | INTEGER | 1 low .. 3 high |

### shift_roster

File: `data/5_optional/shift_roster.parquet`; metadata rows: **10,317**.

Role-level staffing. Slot techs drive repair capacity.
Rows: 10,317 · Key: `assignment_id`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `assignment_id` | VARCHAR | Assignment |
| `gaming_date` | DATE | Gaming day |
| `shift` | VARCHAR | day \| swing \| grave |
| `role` | VARCHAR | slot_tech \| floor_attendant \| beverage_server \| security_officer |
| `zone_id` | VARCHAR | Zone; null = floor-wide |
| `start_utc` | TIMESTAMP | Shift start |
| `end_utc` | TIMESTAMP | Shift end |
| `planned_headcount` | INTEGER | Planned |
| `actual_headcount` | INTEGER | Worked |

### visitor_profile_monthly

File: `data/5_optional/visitor_profile_monthly.parquet`; metadata rows: **42**.

Fictional exit-intercept survey of ALL guests, carded or not.
Rows: 42 · Key: `month, survey_metric`

| Column | Actual DuckDB type | Meaning from dictionary |
| --- | --- | --- |
| `month` | VARCHAR | YYYY-MM |
| `survey_metric` | VARCHAR | Metric |
| `estimate` | DOUBLE | Estimate |
| `standard_error` | DOUBLE | Sampling SE |
| `sample_size` | INTEGER | Respondents |
| `unit` | VARCHAR | share \| minutes \| usd |
| `eligibility` | VARCHAR | Who could be sampled |
| `measurement_method` | VARCHAR | How it was measured |
