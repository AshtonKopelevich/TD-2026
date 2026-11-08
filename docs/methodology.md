# Methodology and implementation status

Stage 1 inventories source schemas and validates source identity/declared keys.
Stage 2 materializes the machine-day mart; no statistical classifications or
causal conclusions have been computed.

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

Statistical methodology, forecast validation and accounting checks will be
documented alongside implementation in their respective stages. The proposed
definitions and unresolved choices remain in `mart_contracts.md`.
