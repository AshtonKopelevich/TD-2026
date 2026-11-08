"""Small known-answer Parquet fixtures; never depend on the full data release."""

import hashlib
from pathlib import Path

import duckdb
import pytest

from casino_pipeline.contracts import SourceContract
from casino_pipeline.database import build_connection


@pytest.fixture
def connection():
    with build_connection() as con:
        yield con


@pytest.fixture
def tiny_source(tmp_path):
    # Apostrophe exercises path quoting as well as paths containing spaces.
    dataset = tmp_path / "team's sample data"
    data = dataset / "data"
    data.mkdir(parents=True)
    path = data / "example.parquet"
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE example (id VARCHAR, amount BIGINT)")
        con.execute("INSERT INTO example VALUES ('a', 10), ('b', 20)")
        con.table("example").write_parquet(str(path))
    finally:
        con.close()
    contract = SourceContract("example", "example.parquet", ("id",), {"amount": "BIGINT"})
    manifest = {"version": "0.9.0-draft", "files": [{"path": path.name, "rows": 2,
                "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    return dataset, contract, manifest
