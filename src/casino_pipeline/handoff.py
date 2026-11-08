"""Stage-eight artifact inspection, dictionary, exports and optional Flask smoke checks."""

from datetime import date,datetime,timedelta,timezone
import importlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote,urlencode
import warnings

import duckdb

from .database import quote_identifier
from .export import export_marts
from .manifest import write_json
from .validate import sha256_file


MART_NAMES = frozenset('''mart_machine_daily mart_machine_month mart_floor_daily mart_zone_daily
 mart_benchmark_month mart_player_month mart_visits_month mart_comps_daily mart_comps_tier_month
 mart_tickets mart_downtime_hourly mart_machine_scorecard mart_forecast mart_actions'''.split())


def read_manifest(con):
    return json.loads(con.execute('SELECT document FROM metadata.build_manifest').fetchone()[0])


def fingerprints(con,manifest):
    result = {}
    for mart in manifest['marts_built']:
        expressions = []
        for col in sorted(mart['columns'],key=lambda col:col['name']):
            name = col['name']
            if name=='prediction_frozen_at_utc':
                continue  # Deliberately changes at each build; not analytical output.
            expression = quote_identifier(name)
            if col['type'] in ('DOUBLE','FLOAT'):
                expression = f'round({expression},8)'
            elif col['type'].startswith('DECIMAL') and int(col['type'].split(',')[1].rstrip(')'))>6:
                expression = f'round({expression},6)'
            expressions.append(expression)
        table = '.'.join(quote_identifier(part) for part in mart['name'].split('.'))
        n,xor,total = con.execute(f"SELECT count(*),bit_xor(hash({','.join(expressions)})),sum(hash({','.join(expressions)})) FROM {table}").fetchone()
        result[mart['name']] = {'rows':n,'xor':str(xor or 0),'sum':str(total or 0)}
    return result


def baseline_snapshot(path):
    if not Path(path).is_file():
        return None
    try:
        with duckdb.connect(str(path),read_only=True) as con:
            manifest = read_manifest(con)
            return {'manifest':manifest,'fingerprints':fingerprints(con,manifest)}
    except (OSError,ValueError,KeyError,duckdb.Error):
        return None


def inspect_database(path,require_all=True):
    checks = []
    def check(name,passed,detail=None):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    with duckdb.connect(str(path),read_only=True) as con:
        manifest = read_manifest(con)
        expected = {mart['name'].split('.')[1]:mart for mart in manifest['marts_built']}
        actual = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name='marts'").fetchall()}
        check('published_mart_set',actual==set(expected) and (not require_all or actual==MART_NAMES),sorted(actual))
        check('published_build_status',manifest['status']=='passed',manifest['build_id'])
        check('no_source_views',con.execute("SELECT count(*) FROM duckdb_views() WHERE schema_name IN ('raw','staging')").fetchone()[0]==0)
        for name,mart in expected.items():
            if name not in actual:
                continue
            table = 'marts.'+quote_identifier(name)
            described = con.execute(f'DESCRIBE {table}').fetchall()
            schema = {row[0]:(row[1],row[2]=='YES') for row in described}
            declared = {col['name']:(col['type'],col['nullable']) for col in mart['columns']}
            check(name+'.schema',schema==declared)
            check(name+'.rows',con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==mart['rows'],mart['rows'])
            keys = con.execute("""SELECT constraint_column_names FROM duckdb_constraints()
                WHERE schema_name='marts' AND table_name=? AND constraint_type='PRIMARY KEY'""",[name]).fetchall()
            check(name+'.primary_key',keys==[(mart['key'],)],mart['key'])
        # Representative parameterized queries use only physical marts.
        if require_all and actual==MART_NAMES:
            sample = con.execute('SELECT machine_id,zone_id,gaming_date FROM marts.mart_machine_daily ORDER BY machine_id,gaming_date LIMIT 1').fetchone()
            machine,zone,day = sample
            count = con.execute('SELECT count(*) FROM marts.mart_machine_daily WHERE machine_id=? AND gaming_date BETWEEN ? AND ?',
                                [machine,day,day+timedelta(days=6)]).fetchone()[0]
            check('consumer.machine_date_filter',count>0)
            check('consumer.zone_aggregation',len(con.execute('''SELECT zone_id,sum(coin_in_usd)/nullif(sum(available_seconds)/3600.0,0)
                FROM marts.mart_zone_daily WHERE zone_id=? GROUP BY zone_id''',[zone]).fetchall())==1)
            check('consumer.forecast_and_budget',con.execute('SELECT count(*) FROM diagnostics.forecast_selection').fetchone()[0]==1
                  and con.execute('SELECT count(*) FROM diagnostics.action_portfolio').fetchone()[0]==1)
        summary = {'build_id':manifest['build_id'],'passed':all(c['passed'] for c in checks),'checks':checks,
                   'marts':manifest['marts_built']}
        return summary,manifest,fingerprints(con,manifest)


def dashboard_smoke(path, routes=None):
    """Use Flask's in-process client; no web server or external messages."""
    root = Path(__file__).resolve().parents[2]
    os.environ['CASINO_DB'] = str(Path(path).resolve())
    if str(root) not in sys.path:
        sys.path.insert(0,str(root))
    results = []
    try:
        module = importlib.import_module('dashboard.app')
        data = importlib.import_module('dashboard.data')
        if data.DB_PATH.resolve()!=Path(path).resolve():
            raise ValueError('Dashboard module is already bound to another database; run the check in a fresh process')
        module.app.config['TESTING'] = True
        with duckdb.connect(str(path),read_only=True) as con:
            machine,bank,day = con.execute('SELECT machine_id,bank_id,gaming_date FROM marts.mart_machine_daily ORDER BY machine_id,gaming_date LIMIT 1').fetchone()
        routes = routes if routes is not None else ['/','/verdict','/machines','/demand','/downtime','/guests','/forecast','/plan',
                  '/machines/'+quote(machine,safe=''),'/machines?'+urlencode({'bank':bank,'start':day.isoformat(),'end':(day+timedelta(days=6)).isoformat()})]
        with module.app.test_client() as client,warnings.catch_warnings():
            warnings.simplefilter('ignore',FutureWarning)
            for route in routes:
                try:
                    response = client.get(route)
                    results.append({'route':route,'status':response.status_code,'passed':response.status_code==200})
                except Exception as error:
                    results.append({'route':route,'passed':False,'error':type(error).__name__+': '+str(error).splitlines()[0]})
    except Exception as error:
        return {'requested':True,'passed':False,'error':type(error).__name__+': '+str(error),'routes':results}
    return {'requested':True,'passed':all(r['passed'] for r in results),'routes':results,
            'scope':'Route/query smoke only; not visual or semantic approval of dashboard findings.'}


def dictionary_text(manifest):
    lines = ['# Generated mart data dictionary','',f"Build: `{manifest['build_id']}`; source release: `{manifest.get('source_release','unknown')}`.",
      '', 'Physical tables require no original source files. Money is dollars; ratios are fractions. UTC timestamps are naive TIMESTAMP values in the database. Nullable values are unknown/unavailable, not zero.',
      '', 'Definitions and analytical limitations: docs/mart_contracts.md, docs/methodology.md and docs/app_handoff.md in the repository.','']
    for mart in manifest['marts_built']:
        lines += [f"## {mart['name']}",'',f"Rows: {mart['rows']:,}. Key: {', '.join(mart['key'])}.",'',
                  '| Column | SQL type | Nullable |','| --- | --- | --- |']
        lines += [f"| `{col['name']}` | {col['type']} | {'yes' if col['nullable'] else 'no'} |" for col in mart['columns']]
        lines.append('')
    return '\n'.join(lines)


def write_text(path,text):
    from uuid import uuid4
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(text+'\n',encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize_handoff(database,output_dir,formats=(),check_dashboard=False,baseline=None,rebuilt=True):
    database,output_dir = Path(database).resolve(),Path(output_dir).resolve()
    inspection,manifest,current = inspect_database(database)
    if not inspection['passed']:
        raise ValueError('Published artifact failed handoff inspection')
    source = Path(manifest.get('dataset_path','/nonexistent-source')).resolve()
    if output_dir==source or source in output_dir.parents:
        raise ValueError('Handoff output must be outside source data')
    comparison = {'status':'no_previous_artifact' if rebuilt else 'reused_existing_artifact'}
    if baseline:
        before = baseline['manifest']
        same_inputs = (before.get('source_manifest_sha256')==manifest.get('source_manifest_sha256')
            and before.get('analytical_defaults')==manifest.get('analytical_defaults')
            and before.get('action_configuration',{}).get('sha256')==manifest.get('action_configuration',{}).get('sha256')
            and before.get('duckdb_version')==manifest.get('duckdb_version'))
        changed = [name for name in sorted(set(current)|set(baseline['fingerprints']))
                   if current.get(name)!=baseline['fingerprints'].get(name)]
        comparison = {'status':('matched' if not changed else 'changed') if same_inputs else 'inputs_or_engine_changed',
            'previous_build_id':before['build_id'],'changed_tables':changed,
            'scope':'Order-independent diagnostic hashes: float rounding 8 places, high-scale decimals 6 places; freeze timestamps excluded. Not cryptographic proof.'}
    with duckdb.connect(str(database),read_only=True) as con:
        export = export_marts(con,output_dir,manifest,formats)
    dashboard = dashboard_smoke(database) if check_dashboard else {'requested':False,'passed':None}
    report = {'build_id':manifest['build_id'],'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'database':str(database),'database_bytes':database.stat().st_size,'database_sha256':sha256_file(database),
        'artifact_passed':inspection['passed'],'dashboard':dashboard,'rebuild_comparison':comparison,
        'fingerprints':current,'checks':inspection['checks'],'exports':export,
        'consumer_notes':[
            'Action benefit_low_usd/high_usd are BEFORE proposal charges; subtract total_cost_usd for net scenario display.',
            'No proposals configured is not an analytical recommendation to preserve the entire budget.',
            'Unavailable hidden/protective/policy flags are NULL; do not display them as tested negatives.',
            'Downtime losses are gross estimates; missing peer coverage is not zero loss and scenario bounds are not confidence intervals.',
        ]}
    report['passed'] = inspection['passed'] and (dashboard.get('passed') is not False)
    return save_handoff_report(output_dir, report, manifest)


def recheck_dashboard_failures(output_dir):
    """Retain earlier results and retry only failed routes against the same artifact."""
    output_dir = Path(output_dir).resolve()
    pointer = json.loads((output_dir/'reports'/'latest_handoff.json').read_text(encoding='utf-8'))
    report = json.loads(Path(pointer['report']).read_text(encoding='utf-8'))
    database = Path(report['database'])
    if sha256_file(database) != report['database_sha256']:
        raise ValueError('Database changed since handoff; run a new handoff inspection')
    with duckdb.connect(str(database), read_only=True) as con:
        manifest = read_manifest(con)
    if manifest['build_id'] != report['build_id']:
        raise ValueError('Handoff build does not match database')
    failed = [r for r in report['dashboard'].get('routes', []) if not r['passed']]
    if not failed:
        return report
    retry = dashboard_smoke(database, routes=[r['route'] for r in failed])
    replacements = {r['route']:r for r in retry['routes']}
    report.setdefault('dashboard_rechecks', []).append({
        'at_utc':datetime.now(timezone.utc).isoformat(), 'previous_failures':failed, 'result':retry})
    dashboard = report['dashboard']
    dashboard['routes'] = [replacements.get(r['route'], r) for r in dashboard['routes']]
    dashboard['passed'] = retry['passed'] and all(r['passed'] for r in dashboard['routes'])
    if retry.get('error'):
        dashboard['error'] = retry['error']
    else:
        dashboard.pop('error', None)
    report['passed'] = report['artifact_passed'] and dashboard['passed']
    return save_handoff_report(output_dir, report, manifest)


def save_handoff_report(output_dir, report, manifest):
    output_dir = Path(output_dir)
    database = report['database']
    dashboard = report['dashboard']
    formats = report['exports']['formats']
    comparison = report['rebuild_comparison']
    directory = output_dir/'reports'/'runs'/manifest['build_id']
    write_json(directory/'handoff.json',report)
    write_text(directory/'data_dictionary.md',dictionary_text(manifest))
    lines = ['# Pipeline handoff','',f"Build: `{manifest['build_id']}`",'',
        f"Database: `{database}`",f"Artifact checks: {'passed' if report['artifact_passed'] else 'failed'}.",
        f"Rebuild comparison: {comparison['status']}.",'', '| Mart | Rows |','| --- | ---: |']
    lines += [f"| {mart['name']} | {mart['rows']:,} |" for mart in manifest['marts_built']]
    lines += ['',f"Exports: {', '.join(formats) or 'not requested'}.",
              f"Dashboard smoke: {'passed' if dashboard.get('passed') else 'failed' if dashboard.get('passed') is False else 'not requested'}.",'',
              '## Consumer interpretation notes','']+[f'- {note}' for note in report['consumer_notes']]
    if dashboard.get('requested'):
        lines += ['', '## Dashboard routes','']
        lines += [f"- {r['route']}: {r.get('status',r.get('error'))}" for r in dashboard.get('routes',[])]
        if dashboard.get('error'):
            lines.append(dashboard['error'])
    write_text(directory/'handoff.md','\n'.join(lines))
    write_text(output_dir/'reports'/'handoff.md','\n'.join(lines))
    write_json(output_dir/'reports'/'latest_handoff.json',{'build_id':manifest['build_id'],'report':str(directory/'handoff.json'),
              'dictionary':str(directory/'data_dictionary.md'),'passed':report['passed']})
    return report
