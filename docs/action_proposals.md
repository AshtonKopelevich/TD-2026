# Action proposal configuration

The pipeline prices a proposed portfolio; it does not infer causal effects or
automatically choose actions. The default config/action_proposals.csv contains
only a header, yielding a typed empty mart and $100,000 unallocated.

Copy that file and pass `--action-proposals path/to/file.csv`, or populate it
directly. All monetary inputs are plain dollar amounts without currency symbols.
Selected proposals are hypothetical analytics outputs, not executed operations.

## Fields

| Input | Meaning |
| --- | --- |
| proposal_line_id | Unique row identifier |
| action_type_id | Existing catalogue ID, such as A-REPLACE-LEASE |
| target_type, target_id | Explicit current target; property target ID is property |
| selected | Explicit true/false or 1/0 |
| quantity | Positive integer; individual machine/bank/zone/manufacturer rows require 1 |
| effect_assumption | Explain the proposed effect and why the evidence supports considering it |
| cost_assumption | Explain included/excluded cost components, especially proposal recurring fees |
| evidence_refs | Table/query references for the supporting evidence |
| measurement_metric | Expected-contribution or other stated success measure |
| control_definition | Comparison/control group or evaluation design |
| limitation | Main uncertainty, displacement and overlapping-benefit limitations |
| expected_uplift_usd_per_day | Incremental contribution per action unit/day, BEFORE charges in this proposal |
| low_uplift_usd_per_day, high_uplift_usd_per_day | Scenarios; must bracket expected uplift; negative effects are allowed |
| benefit_days_per_unit | Optional shortened benefit duration; mandatory for funded promotion events |
| downtime_opportunity_cost_usd_per_hour | Nonnegative foregone operating contribution per affected machine-hour; explicit zero is allowed |
| additional_comp_cost_usd | Extra benefit costs in the budget; must explicitly be set, even to zero, for comp-policy proposals |
| forecast_allocation_share | Optional explicit fraction of floor coin-in allocated to this proposal's target scope |
| unit_start_dates | Semicolon-separated ISO dates, one per unit; mandatory for funded promotions |

Funded non-hold actions require all six assumption/evidence/measurement/control/
limitation text fields. Financial actions require all three uplift scenarios;
funded downtime-bearing financial actions require an opportunity-cost rate.
Inspection, survey and comp pilot can be information-only with unknown benefits.
Unselected drafts may leave benefits unconfigured, but catalogue and target rules
still apply. A-HOLD is a zero-cost, zero-uplift property proposal and consumes no
funded action slot.

Target types follow catalogue units: machine, bank, manufacturer, zone, shift,
or property. Shifts use the source names (day, swing, grave). Machine membership
is resolved at the July horizon start from effective placements. Separate rows
identify separate machine/bank/zone/manufacturer targets. Quantity can represent
extra technician heads on the same shift or nonoverlapping promotion events.

## Calculations

For July 1-30:

```text
operating days = max(0, 30 - catalogue lead days)
cash cost = quantity * (unit cost + recurring daily cost * operating days)
            + additional comp cost
```

Recurring billing follows catalogue lead time; delaying activation does not
automatically refund fees. Full purchase/package prices count against the budget.
A leased replacement with 14-day lead costs $2,500 + 16*$55 = $3,380.

Downtime minutes apply per affected machine. A bank move with ten machines and
eight hours each has eighty machine-hours of opportunity loss. Manufacturer
maintenance similarly expands its per-machine downtime. Benefit duration excludes
the per-machine shutdown duration and any explicit activation delay.

```text
benefit before proposal charges = quantity * daily uplift * benefit days per unit
                                 - affected machine-hours * opportunity-cost rate
net benefit = benefit before proposal charges - cash cost
half-effect net benefit = 0.5 * benefit before proposal charges - cash cost
```

The low/high daily scenarios use the same calculation. Inputs must exclude costs
already charged by the proposal; otherwise lease or service charges could be
deducted twice. Do not treat unavoidable fixed expenses as avoidable downtime
opportunity costs. Duration and sequential scheduling assumptions belong in the
effect/cost text; the pipeline does not solve an operational scheduling problem.

Promotion start dates must respect lead time and fit the horizon; event windows
cannot overlap. Prices/quantity limits are enforced across selected rows. Same-
machine move/replacement conflicts expand bank membership; comp pilot and floor-
wide policy change conflict globally. Duplicate selected targets for the same
machine/bank/zone/manufacturer action are rejected.

The optional forecast allocation is context only. Daily forecasts are proportioned
to the supplied target share and activation/duration weights; overlapping unit
days do not multiply the floor baseline. This does not identify causal effects.
Destination feasibility, substitution and joint-intervention effects are not
solved. Portfolio scenario sums may overstate benefits when interventions overlap.
Unknown information value remains NULL rather than being invented as zero.

Outputs: marts.mart_actions, diagnostics.action_targets,
diagnostics.action_portfolio, metadata.action_catalog, metadata.action_configuration.
The frozen configuration contains original input rows and a SHA-256 fingerprint.
