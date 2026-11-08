CREATE TABLE staging.receipt_player_day AS
SELECT player_id,staging.gaming_date(event_at_utc) AS gaming_date,
 sum(cash_receipt_cents*0.01)::DECIMAL(24,2) AS linked_pos_cash_usd,
 sum(cogs_cents*0.01)::DECIMAL(24,2) AS linked_pos_cogs_usd
FROM raw.fnb_transactions WHERE player_id IS NOT NULL GROUP BY player_id,gaming_date;
