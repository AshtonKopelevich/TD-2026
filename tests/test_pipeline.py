import json

import pytest

from casino_pipeline import build


def test_reports_match_and_no_empty_database_published(tmp_path, tiny_source, monkeypatch):
    dataset, contract, manifest = tiny_source
    (dataset / "data" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    original_register = build.register_sources
    original_validate = build.validate_sources
    monkeypatch.setattr(build, "register_sources", lambda c, d: original_register(c, d, [contract]))
    monkeypatch.setattr(build, "validate_sources", lambda c, d, m, i, h: original_validate(c, d, m, i, h, [contract]))
    output = tmp_path / "output"
    result = build.run(dataset, output, verify_hashes=True, sources_only=True)
    assert result["passed"]
    latest = json.loads((output / "reports" / "latest.json").read_text())
    report_dir = output / "reports" / "runs" / latest["build_id"]
    saved = json.loads((report_dir / "manifest.json").read_text())
    assert saved["marts_built"] == []
    assert saved["build_id"] == result["build_id"]
    assert not (output / "casino.duckdb").exists()


def test_output_cannot_overwrite_sources(tiny_source):
    dataset, _, _ = tiny_source
    with pytest.raises(ValueError, match="outside the source"):
        build.run(dataset, dataset / "reports")
