"""Build metadata, source identity and atomic JSON report writes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import uuid
import platform

import duckdb
import numpy

from . import __version__
from .constants import analytical_defaults
from .validate import sha256_file


def git_revision(root):
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def create_manifest(dataset, source_manifest, inventory, validation):
    declared = {entry["path"]: entry for entry in source_manifest["files"]}
    verified = {check["check"]: check["passed"] for check in validation["checks"]}
    return {"build_id": str(uuid.uuid4()), "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": __version__, "duckdb_version": duckdb.__version__,
            "python_version":platform.python_version(),"numpy_version":numpy.__version__,
            "pipeline_code_sha256":code_fingerprint(),
            "git_revision": git_revision(Path(__file__).resolve().parents[2]),
            "stage": "1_sources", "status": "passed" if validation["passed"] else "failed",
            "dataset_path": str(dataset), "source_release": source_manifest.get("version"),
            "source_manifest_sha256": sha256_file(dataset / "data" / "manifest.json"),
            "analytical_defaults": analytical_defaults(), "marts_built": [],
            "sources": [{**entry, "declared_sha256": declared.get(entry["path"], {}).get("sha256"),
                         "sha256_verified": verified.get(f"{entry['table']}.sha256", False)}
                        for entry in inventory]}


def code_fingerprint():
    """Fingerprint pipeline implementation/lockfile without reading raw datasets."""
    import hashlib
    root = Path(__file__).resolve().parents[2]
    paths = list((root/'src'/'casino_pipeline').rglob('*.py'))+list((root/'sql').rglob('*.sql'))
    paths += [root/name for name in ('run_all.py','pyproject.toml','uv.lock') if (root/name).is_file()]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode()+b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
