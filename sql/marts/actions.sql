-- src/casino_pipeline/actions.py creates the typed mart from validated CSV
-- proposals. Preserve the complete price catalogue even when the mart is empty.
CREATE TABLE metadata.action_catalog AS SELECT * FROM raw.action_catalog;
