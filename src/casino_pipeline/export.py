"""Stream deterministic mart exports through DuckDB; never load full DataFrames."""

from pathlib import Path
import uuid

from .database import quote_identifier
from .manifest import write_json
from .validate import sha256_file


def export_marts(con,output_dir,manifest,formats):
    formats = tuple(sorted(set(formats)))
    if any(fmt not in ('csv','parquet') for fmt in formats):
        raise ValueError('Supported exports are csv and parquet')
    base = Path(output_dir).resolve()/'exports'/manifest['build_id']
    source = Path(manifest.get('dataset_path','/nonexistent-source')).resolve()
    if base==source or source in base.parents:
        raise ValueError('Exports must not overwrite source data')
    records = []
    for mart in manifest['marts_built']:
        schema,name = mart['name'].split('.')
        table = quote_identifier(schema)+'.'+quote_identifier(name)
        order = ','.join(quote_identifier(key) for key in mart['key'])
        projection = ','.join(quote_identifier(col['name']) for col in mart['columns'])
        for fmt in formats:
            path = base/fmt/(name+'.'+fmt)
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
            literal = "'"+temporary.as_posix().replace("'","''")+"'"
            options = ("FORMAT PARQUET, COMPRESSION ZSTD" if fmt=='parquet' else
                "FORMAT CSV, HEADER TRUE, NULL '', DATEFORMAT '%Y-%m-%d', TIMESTAMPFORMAT '%Y-%m-%dT%H:%M:%S.%fZ'")
            try:
                con.execute(f'COPY (SELECT {projection} FROM {table} ORDER BY {order}) TO {literal} ({options})')
                if fmt=='parquet':
                    rows = con.execute('SELECT num_rows FROM parquet_file_metadata(?)',[str(temporary)]).fetchone()[0]
                    observed = {r[0]:r[1] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(temporary)]).fetchall()}
                    expected = {col['name']:col['type'] for col in mart['columns']}
                    if observed!=expected:
                        raise ValueError(f'Export schema mismatch: {mart["name"]}')
                else:
                    relation = con.read_csv(str(temporary),header=True,auto_detect=False,
                        columns={col['name']:'VARCHAR' for col in mart['columns']})
                    rows = relation.aggregate('count(*)').fetchone()[0]
                if rows!=mart['rows']:
                    raise ValueError(f'Export row count mismatch: {mart["name"]}')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            records.append({'table':mart['name'],'format':fmt,'rows':rows,'path':str(path),
                            'bytes':path.stat().st_size,'sha256':sha256_file(path)})
    report = {'build_id':manifest['build_id'],'formats':list(formats),'files':records}
    if formats:
        write_json(base/'manifest.json',report)
        write_json(Path(output_dir)/'exports'/'latest.json',{'build_id':manifest['build_id'],'manifest':str(base/'manifest.json')})
    return report
