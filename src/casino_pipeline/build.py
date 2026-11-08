"""Validate sources, build the machine-day mart, and publish a standalone database."""

import argparse
import logging
import json
from pathlib import Path
import tempfile

import duckdb

from .database import build_connection
from .manifest import create_manifest, write_json
from .sources import read_source_manifest, register_sources
from .validate import validate_sources
from .machine_daily import build_machine_daily, validate_machine_daily, mart_inventory, SCHEMA, NULLABLE

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def run(dataset, output_dir, verify_hashes=False, sources_only=False):
    dataset, output_dir = Path(dataset).resolve(), Path(output_dir).resolve()
    # Never allow an output report to overwrite any source dataset file.
    if output_dir == dataset or dataset in output_dir.parents:
        raise ValueError("Output directory must be outside the source dataset")
    source_manifest = read_source_manifest(dataset)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".casino-build-", dir=output_dir) as temporary:
        database = Path(temporary) / "casino.duckdb"
        with build_connection(database) as con:
            inventory = register_sources(con, dataset)
            LOGGER.info("Registered %s Parquet source views", len(inventory))
            validation = validate_sources(con, dataset, source_manifest, inventory, verify_hashes)
            marts = []
            if validation["passed"] and not sources_only:
                build_machine_daily(con)
                validation["checks"].extend(validate_machine_daily(con))
                validation["passed"] = all(c["passed"] for c in validation["checks"])
                if validation["passed"]:
                    for column in SCHEMA:
                        if column not in NULLABLE:
                            con.execute(f'ALTER TABLE marts.mart_machine_daily ALTER COLUMN "{column}" SET NOT NULL')
                    con.execute("ALTER TABLE marts.mart_machine_daily ADD PRIMARY KEY (machine_id, gaming_date)")
                    marts.append(mart_inventory(con))
            manifest = create_manifest(dataset, source_manifest, inventory, validation)
            manifest.update(stage="1_sources" if sources_only else "2_machine_daily", marts_built=marts)
            validation["build_id"] = manifest["build_id"]
            validation["scope"] += " Machine-day schema, coverage, intervals, meters, accounting and ratios." if not sources_only else ""
            if validation["passed"] and not sources_only:
                con.execute("CREATE TABLE metadata.build_manifest AS SELECT ?::JSON AS document", [json.dumps(manifest)])
                con.execute("CREATE TABLE diagnostics.validation AS SELECT ?::JSON AS document", [json.dumps(validation)])
                con.execute("CREATE TABLE metadata.mart_columns (table_name VARCHAR, column_name VARCHAR, sql_type VARCHAR, nullable BOOLEAN)")
                con.executemany("INSERT INTO metadata.mart_columns VALUES (?,?,?,?)", [
                    (mart["name"], column["name"], column["type"], column["nullable"])
                    for mart in marts for column in mart["columns"]])
                # Physical marts must work without any connection to the original files.
                con.execute("DROP SCHEMA raw CASCADE")
                con.execute("DROP SCHEMA staging CASCADE")
                con.execute("CHECKPOINT")
        if validation["passed"] and not sources_only:
            try:
                # Writer is closed before replacement. A failed replacement preserves the old file.
                database.replace(output_dir / "casino.duckdb")
                LOGGER.info("Published %s (%s machine-days)", output_dir / "casino.duckdb", marts[0]["rows"])
            except OSError as error:
                validation["passed"] = False
                validation["checks"].append({"check": "database.publication", "passed": False,
                                              "detail": str(error)})
                manifest["status"] = "failed"
    report_dir = output_dir / "reports" / "runs" / manifest["build_id"]
    validation["build_id"] = manifest["build_id"]
    write_json(report_dir / "validation.json", validation)
    write_json(report_dir / "manifest.json", manifest)
    # Latest is just a pointer to one complete run, published after both reports.
    write_json(output_dir / "reports" / "latest.json",
               {"build_id": manifest["build_id"], "status": manifest["status"],
                "report_directory": str(report_dir)})
    failed = [c["check"] for c in validation["checks"] if not c["passed"]]
    LOGGER.info("Source release: %s; checks: %s; failures: %s",
                manifest["source_release"], len(validation["checks"]), len(failed))
    for name in failed:
        LOGGER.error("Failed check: %s", name)
    LOGGER.info("Reports: %s", report_dir)
    if sources_only:
        LOGGER.info("Sources-only mode: no database published")
    return validation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dashboard-royale-main")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    parser.add_argument("--verify-hashes", action="store_true", help="Also read each Parquet file to verify its SHA-256")
    parser.add_argument("--sources-only", action="store_true", help="Run stage-one checks without building/publishing marts")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return 0 if run(args.dataset, args.output_dir, args.verify_hashes, args.sources_only)["passed"] else 1
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        LOGGER.error("Source setup failed: %s", error)
        return 1
