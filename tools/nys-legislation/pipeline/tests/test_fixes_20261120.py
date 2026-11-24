"""Nov 20 2026: a long-law window read must not replace a fuller whole-law re-ask answer (B82)."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import extract_duties as ed  # noqa: E402

P = F = 0
def check(name, ok):
    global P, F
    if ok: P += 1
    else: F += 1; print("FAIL", name)

tm = ed.TEXT_MARKED
if not (tm / "2011-A55.txt").exists() or not (ed.PACKETS_ROOT / "2011" / "long" / "results" / "2011-A55__w1.json").exists():
    print("skipped: cache absent"); print("0 passed, 0 failed"); sys.exit(0)
check("A55 windows thinner than its whole re-ask", ed.long_window_thinner("2011-A55", (tm / "2011-A55.txt").read_text()))
check("S6732 windows thinner by unique quotes (68 vs 95)", ed.long_window_thinner("2011-S6732", (tm / "2011-S6732.txt").read_text()))
check("A8691 windows thinner by unique quotes (57 vs 73)", ed.long_window_thinner("2011-A8691", (tm / "2011-A8691.txt").read_text()))
check("a law over MAX_CHARS is never kept whole", not ed.long_window_thinner("2011-A55", "x" * (ed.MAX_CHARS + 1)))
check("flag on", ed.APPLY_LONG_KEEP_WHOLE)
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
