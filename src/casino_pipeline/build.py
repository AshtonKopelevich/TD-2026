"""Validate sources and publish the implemented analytical marts in one database."""

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
from .descriptive import CONTRACTS, validate_inputs, build_descriptive, validate_descriptive, finalize_contract
from .guests import CONTRACTS as GUEST_CONTRACTS, validate_guest_inputs, build_guests, validate_guests
from .analysis.downtime import CONTRACTS as DOWNTIME_CONTRACTS, validate_inputs as validate_downtime_inputs, build_downtime, validate_downtime

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def run(dataset, output_dir, verify_hashes=False, sources_only=False, stage=5):
    if stage not in (1, 2, 3, 4, 5):
        raise ValueError("Implemented stages are 1 through 5")
    sources_only = sources_only or stage == 1
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
                if validation["passed"] and stage >= 3:
                    validation["checks"].extend(validate_inputs(con))
                    validation["passed"] = all(c["passed"] for c in validation["checks"])
                    if validation["passed"]:
                        build_descriptive(con)
                        validation["checks"].extend(validate_descriptive(con))
                        validation["passed"] = all(c["passed"] for c in validation["checks"])
                        if validation["passed"]:
                            marts.extend(finalize_contract(con, contract) for contract in CONTRACTS)
                if validation["passed"] and stage >= 4:
                    validation["checks"].extend(validate_guest_inputs(con))
                    validation["passed"] = all(c["passed"] for c in validation["checks"])
                    if validation["passed"]:
                        build_guests(con)
                        validation["checks"].extend(validate_guests(con))
                        validation["passed"] = all(c["passed"] for c in validation["checks"])
                        if validation["passed"]:
                            marts.extend(finalize_contract(con, contract) for contract in GUEST_CONTRACTS)
                if validation["passed"] and stage >= 5:
                    validation["checks"].extend(validate_downtime_inputs(con))
                    validation["passed"] = all(c["passed"] for c in validation["checks"])
                    if validation["passed"]:
                        build_downtime(con)
                        validation["checks"].extend(validate_downtime(con))
                        validation["passed"] = all(c["passed"] for c in validation["checks"])
                        if validation["passed"]:
                            marts.extend(finalize_contract(con, contract) for contract in DOWNTIME_CONTRACTS)
            manifest = create_manifest(dataset, source_manifest, inventory, validation)
            stages = {1: "1_sources", 2: "2_machine_daily", 3: "3_descriptive", 4: "4_guests", 5: "5_downtime"}
            manifest.update(stage=stages[1 if sources_only else stage], marts_built=marts)
            validation["build_id"] = manifest["build_id"]
            validation["scope"] += " Machine-day schema, coverage, intervals, meters, accounting and ratios." if not sources_only else ""
            if stage >= 3 and not sources_only:
                validation["scope"] += " Descriptive marts: keys, context coverage, sums, traffic, accounting and benchmark reconciliation."
            if stage >= 4 and not sources_only:
                validation["scope"] += " Guests: player/visit grain, carded meters, receipt/ledger links, cohort and points accounting."
            if stage >= 5 and not sources_only:
                validation["scope"] += " Downtime: interval partitioning, hourly/daily reconciliation, ticket timing, peer estimates and pseudo-outage coverage."
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
                LOGGER.info("Published %s (%s marts)", output_dir / "casino.duckdb", len(marts))
                for mart in marts:
                    LOGGER.info("  %s: %s rows", mart["name"], mart["rows"])
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
    parser.add_argument("--stage", type=int, choices=(1, 2, 3, 4, 5), default=5, help="Build through this stage (default: 5)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return 0 if run(args.dataset, args.output_dir, args.verify_hashes, args.sources_only, args.stage)["passed"] else 1
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        LOGGER.error("Pipeline failed: %s", error)
        return 1
