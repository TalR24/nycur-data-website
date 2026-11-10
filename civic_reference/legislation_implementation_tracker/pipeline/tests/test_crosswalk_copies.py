#!/usr/bin/env python3
"""The agency crosswalk is kept in two places that must be byte-identical
(review of Nov 10 2026, finding 13): the pipeline copy that agency_canon.py
and the builders read, and the copy the pages fetch. This fails when they differ.

    python3 civic_reference/legislation_implementation_tracker/pipeline/tests/test_crosswalk_copies.py
"""
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PIPELINE_COPY = REPO / "pipeline" / "agency_crosswalk.json"
SITE_COPY = REPO / "civic_reference" / "legislation_implementation_tracker" / "data" / "agency_crosswalk.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_crosswalk_copies_identical():
    assert PIPELINE_COPY.exists(), f"missing {PIPELINE_COPY}"
    assert SITE_COPY.exists(), f"missing {SITE_COPY}"
    a, b = digest(PIPELINE_COPY), digest(SITE_COPY)
    assert a == b, (f"agency_crosswalk.json copies differ ({PIPELINE_COPY} {a[:12]} vs {SITE_COPY} {b[:12]}); "
                    "rerun pipeline/build_agency_crosswalk.py and copy to both, byte-identical")


if __name__ == "__main__":
    try:
        test_crosswalk_copies_identical()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
    print("ok: agency_crosswalk.json copies are byte-identical")
