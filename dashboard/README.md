# The Gilded Ace dashboard

A Flask dashboard that tells the Dashboard Royale story in seven chapters, built against the
mart contract in `docs/mart_contracts.md`.

## Run it

```sh
pip install -r requirements.txt
python build_duckdb.py          # placeholder database: casino.duckdb, schema `marts`
python -m dashboard.app         # http://127.0.0.1:5000
```

## Switching to the real marts

The dashboard reads the 14 contract tables from the `marts` schema. It looks for a database in
this order:

1. the `CASINO_DB` environment variable
2. `output/casino.duckdb`: where the real pipeline writes, per the contract
3. `casino.duckdb`: the placeholder built by `build_duckdb.py`

Once the pipeline has written `output/casino.duckdb`, restart the app and it uses the real data.
The "placeholder data" banner appears only when the database contains `marts._placeholder`, so it
disappears on its own.

No headline or finding is hard-coded. Every sentence that states a result is computed from the
marts, so the story updates with the real numbers.

## Where things live

| File | What it holds |
| --- | --- |
| `data.py` | Database lookup, the shared filter bar, `T('mart_x')` for schema-qualified names |
| `contract.py` | Display names for contract codes (classifications, event types, action ids, shifts) and which chapter shows each mart |
| `pages.py` | One builder per chapter, plus the opening page |
| `charts.py` | Plotly theme (validated colorblind-safe palette) and the table helper |
| `templates/`, `static/` | Felt, card-stock panels and the oxblood rail |

If the contract renames a code or a column, start with `contract.py`, then search `pages.py`.

## Contract details the dashboard relies on

These are the readings of the draft contract that the pages assume. Confirm them or tell the
dashboard owner.

- **`mart_machine_scorecard.primary_classification`** uses the nine codes in section 5. Each one
  maps to a betting spot on the opening page through `contract.CLASSES`.
- **The adjusted bottom 10** is `adjusted_rank <= 10`. The manager's list is `naive_bottom_10`.
- **`mart_actions.benefit_low_usd` and `benefit_high_usd`** are read as net-benefit scenarios
  (after cost), on the same basis as `net_benefit_usd`. The contract doesn't say.
- **`mart_actions.evidence_refs`** holds mart names separated by semicolons
  (e.g. `mart_downtime_hourly;mart_tickets`). Each becomes a link to the chapter that shows it.
- **`policy_change_candidate`** in `mart_comps_daily` marks the candidate change date(s). The
  chart draws a line on each flagged date.
- **`mart_downtime_hourly.local_hour`** is the local clock hour, and `gaming_date` is the
  6 a.m.-to-6 a.m. gaming day. Shifts: day 06-14, swing 14-22, grave 22-06 (from `shift_roster`).
- **Action names** come from the source `action_catalog.parquet`, with short labels in
  `contract.ACTION_SHORT`.
- **The concentration curve and winner share** are computed per player across the selected
  months from `mart_player_month`, as the contract requires.
