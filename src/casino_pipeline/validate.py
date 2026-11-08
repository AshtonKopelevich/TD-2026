"""Stage-one schema, metadata, optional hash, and declared-key checks."""

import hashlib

from .constants import EXPECTED_SOURCE_RELEASE
from .contracts import SOURCE_CONTRACTS
from .database import quote_identifier


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sources(con, dataset, manifest, inventory, verify_hashes=False, contracts=SOURCE_CONTRACTS):
    checks = []

    def check(name, passed, detail):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    check("source_release", manifest.get("version") == EXPECTED_SOURCE_RELEASE,
          {"expected": EXPECTED_SOURCE_RELEASE, "actual": manifest.get("version")})
    declared = {entry["path"]: entry for entry in manifest["files"]}
    actual = {entry["table"]: entry for entry in inventory}
    for contract in contracts:
        entry = actual[contract.name]
        expected = declared.get(contract.relative_path)
        check(f"{contract.name}.manifest_entry", expected is not None, contract.relative_path)
        if expected is not None:
            for metric in ("rows", "bytes"):
                check(f"{contract.name}.{metric}", entry[metric] == expected.get(metric),
                      {"expected": expected.get(metric), "actual": entry[metric]})
            if verify_hashes:
                digest = sha256_file(dataset / "data" / contract.relative_path)
                check(f"{contract.name}.sha256", digest == expected.get("sha256"), {"actual": digest})
        types = {column["name"]: column["type"] for column in entry["columns"]}
        missing = [key for key in contract.key if key not in types]
        mismatches = {column: {"expected": dtype, "actual": types.get(column)}
                      for column, dtype in contract.required_types.items() if types.get(column) != dtype}
        check(f"{contract.name}.required_schema", not missing and not mismatches,
              {"missing_key_columns": missing, "type_mismatches": mismatches})
        if contract.key and not missing:
            table = f"raw.{quote_identifier(contract.name)}"
            key_sql = ", ".join(quote_identifier(key) for key in contract.key)
            null_sql = " OR ".join(f"{quote_identifier(key)} IS NULL" for key in contract.key)
            nulls = con.execute(f"SELECT count(*) FROM {table} WHERE {null_sql}").fetchone()[0]
            duplicates = con.execute(
                f"SELECT count(*) FROM (SELECT {key_sql} FROM {table} GROUP BY {key_sql} HAVING count(*) > 1)"
            ).fetchone()[0]
            check(f"{contract.name}.key", nulls == 0 and duplicates == 0,
                  {"key": list(contract.key), "null_rows": nulls, "duplicate_groups": duplicates})
    return {"passed": all(c["passed"] for c in checks), "checks": checks,
            "hashes_verified": verify_hashes,
            "scope": "Manifest row counts/bytes, declared keys, and minimum required schemas. No mart or accounting validation yet."}
