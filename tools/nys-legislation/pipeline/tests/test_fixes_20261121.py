"""Nov 21 2026 (B75): a reprint whose only change swaps a disability term for respectful wording is not a record."""
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

f = ed.b75_respectful_swap
check("adjacent swap", f("discriminate against a [hearing impaired] person {{who is deaf or hard of hearing}} or a blind person"))
check("split swap", f("an assistive listening system for use by the {{deaf and hard of}} hearing [impaired]."))
check("handicapped", f("services for [handicapped] persons {{with disabilities}} shall be provided by the department"))
check("new group of deaf students is a record", not f("the department shall provide interpreters for {{deaf students}} in each district"))
check("a real change alongside the swap is a record", not f("the [hearing impaired] person {{who is deaf or hard of hearing}} shall receive {{free}} devices"))
check("no deletion is a record", not f("the {{deaf or hard of hearing}} commission shall meet"))
check("flag on", ed.APPLY_B75)
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
