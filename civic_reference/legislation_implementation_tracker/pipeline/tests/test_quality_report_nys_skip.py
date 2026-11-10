#!/usr/bin/env python3
"""The NYS validator must be skipped, visibly, when its gitignored text cache is absent
(CI checkout): validate_duties.py would count every record as a HARD failure."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monthly_quality_report as m


def test_skip_path():
    d = Path(tempfile.mkdtemp())
    signed = d / "signed"; signed.mkdir()
    (signed / "2025.json").write_text(json.dumps([{}] * 20))
    assert not m.nys_text_cache_usable(d / "missing", signed)
    text = d / "text"; text.mkdir()
    assert not m.nys_text_cache_usable(text, signed)              # empty
    for i in range(5):
        (text / f"{i}.txt").write_text("x")
    assert not m.nys_text_cache_usable(text, signed)              # 5 of 20
    for i in range(5, 19):
        (text / f"{i}.txt").write_text("x")
    assert m.nys_text_cache_usable(text, signed)                  # 19 of 20
    assert "skipped" in m.NYS_SKIP_LINE and "nightly on the Mac" in m.NYS_SKIP_LINE


if __name__ == "__main__":
    test_skip_path(); print("ok: NYS skip guard")
