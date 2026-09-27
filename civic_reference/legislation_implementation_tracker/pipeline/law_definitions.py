#!/usr/bin/env python3
"""Extract a law's own definitions of the generic titles it uses.

Many laws use a generic title ("the director", "the advisory board", "the
office") whose meaning is defined nowhere except inside that same law: a
definitions clause ("the term 'X' means Y"), or an establishing sentence
("there is hereby established within the department an office of alternative
energy") that gives the new body X a parent Y. `definitions(text)` finds
both forms and returns {term (lowercased, articles stripped): entity phrase}.

Used by extract_obligations.py Step 2 to resolve a generic actor through the
SAME law's own text before falling back to the code-title or crosswalk rules.
Reused, not duplicated: this module has no dependency on extract_obligations,
so it can be imported by extract_obligations.py without a cycle.
"""
from __future__ import annotations

import re

ARTICLE_RE = re.compile(r"^(the|a|an|such|said)\s+", re.I)

# Cut an entity phrase at the first clause boundary after the name itself, so
# "the department of buildings, which shall coordinate with..." keeps only
# "the department of buildings".
_CUT_RE = re.compile(r"\s*(,\s|\bthat\b|\bwhich\b|;)", re.I)
MAX_ENTITY_LEN = 3000


def strip_articles(term: str) -> str:
    return ARTICLE_RE.sub("", (term or "").strip().lower()).strip()


def _cut_entity(phrase: str) -> str:
    phrase = (phrase or "").strip()
    m = _CUT_RE.search(phrase)
    if m:
        phrase = phrase[:m.start()]
    return phrase.strip().rstrip(".,;: ").strip()


def _key(term: str) -> str:
    return strip_articles(re.sub(r"\s+", " ", (term or "").strip().lower()))


# "the term "X" means Y." / ""X" means Y." (quote marks: straight or curly)
_Q = '"“”'
_MEANS_RE = re.compile(
    r'(?:the\s+term\s+)?["“]([^"”]{1,80})["”]\s+(?:shall\s+)?means?\s+'
    r'([^.;]{1,400})',
    re.I,
)

# "X shall mean Y." — X is the word/phrase right before "shall mean", usually
# itself quoted a sentence earlier ("...subdivision, "district 75 program"
# shall mean..."), so the same quoted-term pattern also covers the term; this
# catches the unquoted form ("Such term shall mean...") only when a quoted
# name sits immediately before it.
_SHALL_MEAN_RE = re.compile(
    r'["“]([^"”]{1,80})["”]\s+shall\s+mean\s+([^.;]{1,400})', re.I)

# Establishing sentences: "There is hereby established (in|within) the Y
# a(n) office/division/board/council/task force/unit/bureau/committee/
# commission/panel/program (of/for/on) X" -> X's parent is Y.
_UNIT_WORDS_RE = re.compile(
    r"\b(office|division|board|council|task\s+force|unit|bureau|"
    r"committee|commission|panel|program|working\s+group|advisory\s+board)\b",
    re.I)
# The unit-type word can lead ("an office of alternative energy") or trail
# ("a real time enforcement unit"); require it to appear somewhere in the
# captured entity phrase rather than at a fixed position.
_ESTABLISH_RE = re.compile(
    r"there\s+(?:is|shall\s+be)\s+hereby\s+established\s+(?:in|within)\s+"
    r"(?:the\s+)?(?P<parent>[^,.;]{2,80}?)\s+(?:an?)\s+"
    r"(?P<entity>[^.;]{2,200})",
    re.I,
)
# "the mayor shall establish ... X" (an office/board/etc named X; matched
# only when the sentence itself names a parent for X via "of/within/in the Y",
# so we never invent a parent).
_MAYOR_ESTABLISH_RE = re.compile(
    r"the\s+mayor\s+shall\s+establish\s+(?:an?\s+)?"
    r"(?P<entity>[^.;]{2,200})",
    re.I,
)

# "As used in this section/chapter/subchapter..." introduces a definitions
# list; each subsequent "Term. The term "X" means Y." line is picked up by
# _MEANS_RE already run over the whole text, so this pattern only bounds how
# far past the intro sentence we still look (kept for future use / clarity).
_AS_USED_RE = re.compile(
    r"as\s+used\s+in\s+this\s+(section|chapter|subchapter|article|title)\b", re.I)


def definitions(text: str) -> dict[str, str]:
    """term (lowercased, articles stripped) -> defined entity phrase.

    Later matches do not overwrite an earlier one for the same term: the
    first defining sentence for a term in a law is the one to trust.
    """
    text = text or ""
    out: dict[str, str] = {}

    def add(term: str, entity: str) -> None:
        k = _key(term)
        entity = _cut_entity(entity)
        if not k or not entity or k == _key(entity):
            return
        if k not in out:
            out[k] = entity[:400]

    for m in _MEANS_RE.finditer(text):
        add(m.group(1), m.group(2))
    for m in _SHALL_MEAN_RE.finditer(text):
        add(m.group(1), m.group(2))
    for m in _ESTABLISH_RE.finditer(text):
        entity = _cut_entity(m.group("entity"))
        if _UNIT_WORDS_RE.search(entity):
            add(entity, m.group("parent"))
    for m in _MAYOR_ESTABLISH_RE.finditer(text):
        # no explicit parent named in this form; skip unless the entity
        # phrase itself names a parent via "of/within/in the X"
        ent = _cut_entity(m.group("entity"))
        if not _UNIT_WORDS_RE.search(ent):
            continue
        pm = re.search(r"\b(?:within|in|of)\s+(?:the\s+)?([^,.;]{2,80})$", ent, re.I)
        if pm:
            add(ent[:pm.start()].strip(), pm.group(1))

    return out


def definitions_block(text: str, cap: int = MAX_ENTITY_LEN) -> str:
    """The definitions found, formatted for the extraction prompt, capped."""
    d = definitions(text)
    if not d:
        return ""
    lines = [f'- "{term}" = {entity}' for term, entity in d.items()]
    block = "\n".join(lines)
    return block[:cap]


_DEFINING = re.compile(
    r"\b(means|shall mean|the term|as used in this|hereby (established|created)|shall (establish|create|convene|designate|staff)|"
    r"(established|located|created) (with)?in the|shall consist of|shall be (chaired|appointed|staffed)|designated by the mayor)\b",
    re.I)


def defining_sentences(text: str, cap: int = 3000) -> str:
    """The law's own sentences that define a term or establish/staff a body,
    verbatim, for the extraction prompt (Sep 27 2026: which agency convenes a
    board is a judgment the model makes from these; parsing them in code
    resolved only 10 records corpus-wide)."""
    out, used = [], 0
    for sent in re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", text or "")):
        if len(sent) < 20 or not _DEFINING.search(sent):
            continue
        sent = sent[:600]
        if used + len(sent) > cap:
            break
        out.append("- " + sent)
        used += len(sent) + 3
    return "\n".join(out)
