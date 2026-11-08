"""DuckDB lifecycle and safe SQL identifier quoting."""

from contextlib import contextmanager

import duckdb


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def build_connection(path=":memory:"):
    """Source views are temporary build inputs, never published dependencies."""
    con = duckdb.connect(str(path))
    try:
        con.execute("SET TimeZone = 'UTC'")
        for schema in ("raw", "staging", "marts", "diagnostics", "metadata"):
            con.execute(f"CREATE SCHEMA {quote_identifier(schema)}")
        yield con
    finally:
        con.close()
