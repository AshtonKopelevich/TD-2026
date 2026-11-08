"""Two focused export/inspection checks; no earlier analysis test reruns."""

from datetime import datetime
from decimal import Decimal
import json

from casino_pipeline.export import export_marts
from casino_pipeline.handoff import inspect_database,fingerprints
from casino_pipeline.database import build_connection


def seed(con):
    con.execute('''CREATE TABLE marts.sample(id INTEGER PRIMARY KEY,amount DECIMAL(24,2),label VARCHAR,
      when_utc TIMESTAMP,prediction_frozen_at_utc TIMESTAMP);
      INSERT INTO marts.sample VALUES(2,NULL,'comma, and "quote"',NULL,'2026-01-01'),
        (1,0.00,'',TIMESTAMP '2025-01-01 12:00:00','2026-01-01');
      CREATE TABLE marts.empty(id INTEGER PRIMARY KEY,amount DECIMAL(24,2));''')
    marts = []
    for name in ('sample','empty'):
        described = con.execute('DESCRIBE marts.'+name).fetchall()
        marts.append({'name':'marts.'+name,'rows':2 if name=='sample' else 0,'key':['id'],
          'columns':[{'name':r[0],'type':r[1],'nullable':r[2]=='YES'} for r in described]})
    manifest = {'build_id':'fixture','status':'passed','source_release':'fixture','marts_built':marts}
    con.execute('CREATE TABLE metadata.build_manifest AS SELECT ?::JSON AS document',[json.dumps(manifest)])
    return manifest


def test_csv_and_parquet_export_roundtrip_nulls_quotes_and_empty_tables(connection,tmp_path):
    manifest = seed(connection)
    report = export_marts(connection,tmp_path,manifest,('csv','parquet'))
    assert len(report['files'])==4
    path = tmp_path/'exports'/'fixture'/'parquet'/'sample.parquet'
    rows = connection.execute('SELECT id,amount,label FROM read_parquet(?) ORDER BY id',[str(path)]).fetchall()
    assert rows==[(1,Decimal('0.00'),''),(2,None,'comma, and "quote"')]
    csv = tmp_path/'exports'/'fixture'/'csv'/'sample.csv'
    text = csv.read_text()
    assert '2025-01-01T12:00:00.000000Z' in text
    assert (tmp_path/'exports'/'fixture'/'manifest.json').is_file()


def test_self_contained_inspection_and_rebuild_fingerprints(tmp_path):
    path = tmp_path/'fixture.duckdb'
    with build_connection(path) as con:
        manifest = seed(con)
        before = fingerprints(con,manifest)
        con.execute("UPDATE marts.sample SET prediction_frozen_at_utc=TIMESTAMP '2026-02-01'")
        assert fingerprints(con,manifest)==before
        con.execute('UPDATE marts.sample SET amount=1 WHERE id=1')
        assert fingerprints(con,manifest)!=before
        con.execute('DROP SCHEMA raw CASCADE')
        con.execute('DROP SCHEMA staging CASCADE')
    report,_,_ = inspect_database(path,require_all=False)
    assert report['passed']
