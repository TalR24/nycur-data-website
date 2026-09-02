"""
Monthly quality report for the legislation trackers — the standing
decay detector (same pattern as the resolution engine's
quality_reports/: dated report + metrics JSON committed monthly, with
a month-over-month diff up top).

Runs the existing instruments rather than reinventing them:
  1. pipeline/validate_obligations.py --json  (the regression suite
     from the Aug 2026 audit campaign: hard failures + soft counts)
  2. pipeline/validate_against_doris.py       (external check against
     the city's own required-reports register)
  3. <repo>/pipeline/validate_fiscal_impacts.py --json  (the fiscal
     tracker's sibling suite, Sep 2026: invariants, dead-link shape,
     coverage vs the enacted-law universe)

Writes  quality_reports/quality_report_YYYY-MM-DD.{md,json}  under the
implementation tracker (one report for both trackers; the fiscal
metrics are prefixed `fiscal_`).

Sep 2 2026 fix: this wrapper read the validator JSON under the keys
"hard"/"soft" but the validator writes "hard_failures"/"soft_counts",
so every metric was silently dropped, the diff never fired, and the
Aug 20 2026 headline said "clean" over 1,933 hard failures. Any HARD failure or a rising soft count is a
signal to run a quality loop (database-expansion-playbook skill).

Usage:  python3 pipeline/monthly_quality_report.py
        (from civic_reference/legislation_implementation_tracker/)
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parent
REPO = TRACKER.parent.parent
FISCAL_VALIDATOR = REPO / "pipeline" / "validate_fiscal_impacts.py"
OUT_DIR = TRACKER / "quality_reports"


def run(cmd):
    proc = subprocess.run(
        cmd, cwd=TRACKER, capture_output=True, text=True, timeout=1800,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    tag = f"quality_report_{date.today().isoformat()}"
    OUT_DIR.mkdir(exist_ok=True)
    vjson = OUT_DIR / f"{tag}.validator.json"

    rc_v, out_v = run([
        sys.executable, "pipeline/validate_obligations.py",
        "--json", str(vjson),
    ])
    rc_d, out_d = run([sys.executable, "pipeline/validate_against_doris.py"])
    fjson = OUT_DIR / f"{tag}.fiscal.json"
    rc_f, out_f = run([sys.executable, str(FISCAL_VALIDATOR), "--json", str(fjson)])

    metrics = {"_validator_exit": rc_v, "_doris_exit": rc_d, "_fiscal_exit": rc_f}

    def absorb(path: Path, prefix: str) -> None:
        """Both validators write {"hard_failures": {check: [ids]},
        "soft_counts": {check: n}}; flatten to <prefix>hard:<check> = n."""
        if not path.exists():
            return
        raw = json.loads(path.read_text())
        for k, v in (raw.get("hard_failures") or {}).items():
            metrics[f"{prefix}hard:{k}"] = len(v) if isinstance(v, list) else v
        for k, v in (raw.get("soft_counts") or {}).items():
            metrics[f"{prefix}soft:{k}"] = len(v) if isinstance(v, list) else v

    absorb(vjson, "")
    absorb(fjson, "fiscal_")

    # Month-over-month diff vs the newest earlier metrics JSON.
    prev_name, prev = None, {}
    for older in sorted(OUT_DIR.glob("quality_report_*.json"), reverse=True):
        if older.stem != tag and not older.name.endswith((".validator.json", ".fiscal.json")):
            prev_name, prev = older.stem, json.loads(older.read_text())
            break
    delta = []
    for k in sorted(set(metrics) | set(prev)):
        if k.startswith("_"):
            continue
        now_v, then_v = metrics.get(k, 0), prev.get(k, 0)
        if now_v != then_v:
            arrow = "REGRESSION +" if now_v > then_v else "improved -"
            delta.append(f"- **{k}**: {then_v} → {now_v} ({arrow}{abs(now_v - then_v)})")
    if prev and not delta:
        delta = ["- No metric changed. Quiet month."]

    hard_total = sum(
        v for k, v in metrics.items() if k.startswith("hard:") or k.startswith("fiscal_hard:")
    )
    lines = [
        f"# Legislation trackers quality report — {tag}",
        "",
        f"Hard failures: **{hard_total}**"
        + (" — RUN A QUALITY LOOP" if hard_total else " (clean)"),
        "",
    ]
    if prev:
        lines += [f"## Change vs {prev_name}", ""] + delta + [""]
    lines += ["## validate_obligations.py", "```", out_v.strip()[:12000], "```",
              "", "## validate_against_doris.py", "```",
              out_d.strip()[:8000], "```",
              "", "## validate_fiscal_impacts.py (fiscal tracker)", "```",
              out_f.strip()[:8000], "```"]

    (OUT_DIR / f"{tag}.md").write_text("\n".join(lines) + "\n")
    (OUT_DIR / f"{tag}.json").write_text(json.dumps(metrics, indent=1))
    vjson.unlink(missing_ok=True)   # detail lives in the md; keep folder lean
    fjson.unlink(missing_ok=True)
    print("\n".join(lines[:14]))
    print(f"\nwrote {OUT_DIR / (tag + '.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
