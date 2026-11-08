"""Orchestration. Stage one validates inputs; no marts are published yet."""

import argparse
import logging
from pathlib import Path

import duckdb

from .database import build_connection
from .manifest import create_manifest, write_json
from .sources import read_source_manifest, register_sources
from .validate import validate_sources

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def run(dataset, output_dir, verify_hashes=False):
    dataset, output_dir = Path(dataset).resolve(), Path(output_dir).resolve()
    # Never allow an output report to overwrite any source dataset file.
    if output_dir == dataset or dataset in output_dir.parents:
        raise ValueError("Output directory must be outside the source dataset")
    source_manifest = read_source_manifest(dataset)
    with build_connection() as con:
        inventory = register_sources(con, dataset)
        LOGGER.info("Registered %s Parquet source views", len(inventory))
        validation = validate_sources(con, dataset, source_manifest, inventory, verify_hashes)
    manifest = create_manifest(dataset, source_manifest, inventory, validation)
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
    LOGGER.info("Stage 1 only: no mart tables or casino.duckdb published")
    return validation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dashboard-royale-main")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    parser.add_argument("--verify-hashes", action="store_true", help="Also read each Parquet file to verify its SHA-256")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return 0 if run(args.dataset, args.output_dir, args.verify_hashes)["passed"] else 1
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        LOGGER.error("Source setup failed: %s", error)
        return 1
