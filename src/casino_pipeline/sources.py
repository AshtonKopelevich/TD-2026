"""Discover declared Parquet sources and bind views without copying records."""

import json

from .contracts import SOURCE_CONTRACTS
from .database import quote_identifier


def read_source_manifest(dataset):
    path = dataset / "data" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = manifest["files"]
    paths = [entry["path"] for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate file paths in source manifest")
    return manifest


def register_sources(con, dataset, contracts=SOURCE_CONTRACTS):
    inventory = []
    for contract in contracts:
        path = dataset / "data" / contract.relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Required source missing: {contract.relative_path}")
        # Relation API binds paths safely, including apostrophes and spaces.
        name = f"raw.{quote_identifier(contract.name)}"
        literal = "'" + path.as_posix().replace("'", "''") + "'"
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({literal})")
        schema = con.execute(f"DESCRIBE {name}").fetchall()
        rows = con.execute("SELECT num_rows FROM parquet_file_metadata(?)", [str(path)]).fetchone()[0]
        inventory.append({"table": contract.name, "path": contract.relative_path,
                          "bytes": path.stat().st_size, "rows": rows,
                          "columns": [{"name": r[0], "type": r[1]} for r in schema]})
    return inventory
