import json

import pytest

from casino_pipeline.database import quote_identifier
from casino_pipeline.manifest import write_json
from casino_pipeline.sources import read_source_manifest, register_sources
from casino_pipeline.validate import validate_sources


def test_quoted_path_metadata_schema_and_keys(connection, tiny_source):
    dataset, contract, manifest = tiny_source
    inventory = register_sources(connection, dataset, [contract])
    result = validate_sources(connection, dataset, manifest, inventory, True, [contract])
    assert result["passed"]
    assert result["hashes_verified"]
    assert inventory[0]["rows"] == 2
    assert connection.execute("SELECT sum(amount) FROM raw.example").fetchone()[0] == 30


@pytest.mark.parametrize("bad_rows", ["('a', 10), ('a', 20)", "('a', 10), (NULL, 20)"])
def test_bad_keys_fail(connection, tiny_source, bad_rows):
    dataset, contract, manifest = tiny_source
    inventory = register_sources(connection, dataset, [contract])
    connection.execute("DROP VIEW raw.example")
    connection.execute("CREATE TABLE raw.example (id VARCHAR, amount BIGINT)")
    connection.execute(f"INSERT INTO raw.example VALUES {bad_rows}")
    result = validate_sources(connection, dataset, manifest, inventory, contracts=[contract])
    assert not result["passed"]
    assert not next(c for c in result["checks"] if c["check"] == "example.key")["passed"]


def test_manifest_drift_fails(connection, tiny_source):
    dataset, contract, manifest = tiny_source
    inventory = register_sources(connection, dataset, [contract])
    manifest["files"][0].update(rows=999, sha256="incorrect")
    result = validate_sources(connection, dataset, manifest, inventory, True, [contract])
    failures = {c["check"] for c in result["checks"] if not c["passed"]}
    assert failures == {"example.rows", "example.sha256"}


def test_missing_schema_column_fails(connection, tiny_source):
    dataset, contract, manifest = tiny_source
    inventory = register_sources(connection, dataset, [contract])
    inventory[0]["columns"] = [{"name": "id", "type": "VARCHAR"}]
    result = validate_sources(connection, dataset, manifest, inventory, contracts=[contract])
    assert not result["passed"]


def test_missing_file_fails(connection, tiny_source):
    dataset, contract, _ = tiny_source
    with pytest.raises(FileNotFoundError, match="Required source missing"):
        register_sources(connection, dataset / "missing", [contract])


def test_duplicate_manifest_paths_fail(tiny_source):
    dataset, _, manifest = tiny_source
    manifest["files"] *= 2
    (dataset / "data" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        read_source_manifest(dataset)


def test_json_report_replacement(tmp_path):
    path = tmp_path / "reports" / "manifest.json"
    write_json(path, {"status": "first"})
    write_json(path, {"status": "second"})
    assert json.loads(path.read_text())["status"] == "second"
    assert list(path.parent.iterdir()) == [path]


def test_quote_identifier():
    assert quote_identifier('a"b') == '"a""b"'
