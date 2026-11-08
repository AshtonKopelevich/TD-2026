# Methodology and implementation status

Stage 1 only inventories source schemas and validates source identity/declared keys.
No analytical conclusion has been computed. Metadata inventory is not EDA.

Defaults live in `src/casino_pipeline/constants.py` and are snapshotted in each
manifest. Eligibility cutoffs and operational triggers are sensitivity parameters,
not guarantees. Uncalibrated definitions remain `None`; future analytical code must
not silently generate flags that depend on them.

Statistical methodology, forecast validation and accounting checks will be
documented alongside implementation in their respective stages. The proposed
definitions and unresolved choices remain in `mart_contracts.md`.
