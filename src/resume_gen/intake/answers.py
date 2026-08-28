"""The screening-answers bank (SQLite, table ``answers``).

Application forms keep asking the same questions in slightly different words:
"Are you legally authorized to work in Canada?" one day, "Do you have legal
authorization to work in the country of employment?" the next. This store keeps
every answer you've approved, matched back **fuzzily**, so the second form reuses
the first form's answer instead of drafting a fresh one.

Matching is deliberately stdlib-only (normalize + ``difflib``): the questions are
short, the corpus is small, and it keeps the app dependency-free. Two signals are
combined — whole-question similarity and keyword overlap — because forms often
pad a familiar question with boilerplate ("For compliance purposes, …").

Nothing is written here speculatively. Drafted answers only land in the bank once
the user confirms the application (see ``automation.autoapply``), so answers you
rejected never come back to haunt a later form.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from difflib import SequenceMatcher

from . import db

# Below this combined score a stored answer is not considered a match and the
# question gets drafted fresh. Tuned so wording changes match but genuinely
# different questions ("years of experience" vs "notice period") do not.
MATCH_THRESHOLD = 0.72

# A drafted answer that scored at least this against an existing record is filed
# as an alternate phrasing (tag) of it rather than as a new record. Between this
# and MATCH_THRESHOLD is the "related but not the same question" band.
MERGE_THRESHOLD = 0.55

# Dropped before matching: they carry no signal and forms sprinkle them liberally.
# Stemmed at import (see `_STOPWORDS`) so they still match stemmed question text.
_STOPWORDS_RAW = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "do", "does", "did", "you", "your", "yours", "are", "is", "was", "were", "be",
    "been", "have", "has", "had", "will", "would", "can", "could", "should", "if",
    "any", "this", "that", "these", "those", "it", "its", "as", "by", "from",
    "please", "kindly", "briefly", "describe", "tell", "us", "we", "our",
    "purposes", "compliance", "note", "question", "questions", "applicant",
    "candidate", "position", "role", "job", "application", "apply", "applying",
}


def _norm(text: str) -> str:
    """Normalized question text: lowercase, punctuation-free, single-spaced."""
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Suffixes stripped when comparing questions, longest first. This is deliberately
# a crude stemmer rather than a real one: it only has to collapse the handful of
# variations forms actually produce — "salary expectations" vs "expected salary",
# "years of experience" vs "experiences" — without a new dependency.
_SUFFIXES = ("ations", "ation", "ements", "ement", "ings", "ing", "edly",
             "ates", "ate", "ed", "es", "s", "ly")


def _stem(word: str) -> str:
    # British -> American spelling first: forms mix "authorised" and "authorized"
    # freely, and an unmatched spelling otherwise looks like a different question.
    w = word.replace("ise", "ize").replace("isa", "iza")
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def _stem_text(norm: str) -> str:
    return " ".join(_stem(w) for w in norm.split())


# Compared against stemmed tokens, so the list itself has to be stemmed.
_STOPWORDS = {_stem(w) for w in _STOPWORDS_RAW}


def _keywords(stemmed: str) -> set[str]:
    return {w for w in stemmed.split() if w not in _STOPWORDS and len(w) > 2}


def _answer_id(question: str) -> str:
    return hashlib.sha1(_norm(question).encode("utf-8")).hexdigest()[:16]


def score(a: str, b: str) -> float:
    """Similarity of two questions, 0..1.

    Blends whole-string similarity with keyword overlap (Jaccard). The overlap
    term is what lets a padded restatement of a known question still match; the
    sequence term is what stops two questions that merely share vocabulary
    ("years of experience with Python" / "years of experience with Java") from
    scoring as high as a true restatement.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa, sb = _stem_text(na), _stem_text(nb)
    seq = SequenceMatcher(None, sa, sb).ratio()
    ka, kb = _keywords(sa), _keywords(sb)
    overlap = len(ka & kb) / len(ka | kb) if (ka | kb) else 0.0
    return round(0.55 * seq + 0.45 * overlap, 4)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _row_to_answer(row) -> dict | None:
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def list_answers() -> list[dict]:
    """Every banked answer, most-reused first."""
    with db.connect() as conn:
        cur = conn.execute(
            "SELECT data FROM answers ORDER BY times_used DESC, date_added DESC"
        )
        return [a for a in (_row_to_answer(r) for r in cur.fetchall()) if a]


def get_answer(answer_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM answers WHERE id = ?", (answer_id,)
        ).fetchone()
    return _row_to_answer(row) if row else None


def find_match(question: str, *, threshold: float | None = None) -> tuple[dict | None, float]:
    """Best banked answer for `question`, or (None, best_score) if nothing clears
    the threshold. The caller decides what to do with a miss (draft a new one)."""
    cutoff = MATCH_THRESHOLD if threshold is None else threshold
    best, best_score = None, 0.0
    for rec in list_answers():
        s = score(question, rec.get("question", ""))
        # Tags are alternate phrasings collected over time; any one of them
        # matching is as good as the canonical question matching.
        for tag in rec.get("tags") or []:
            s = max(s, score(question, tag))
        if s > best_score:
            best, best_score = rec, s
    if best is not None and best_score >= cutoff:
        return best, best_score
    return None, best_score


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def save_answer(question: str, answer: str, *, tags: list[str] | None = None,
                source_company: str = "", verified: bool = False,
                merge_into: str = "") -> dict:
    """Add (or update) a banked answer.

    `merge_into` is the id of an existing record this question is a restatement
    of: instead of a near-duplicate row, the new phrasing is filed as a tag on
    the original. That is how the bank stays small while its recall grows.
    """
    q, a = (question or "").strip(), (answer or "").strip()
    if not q or not a:
        raise ValueError("Both a question and an answer are required.")

    if merge_into:
        rec = get_answer(merge_into)
        if rec is not None:
            tagset = list(rec.get("tags") or [])
            if _norm(q) != _norm(rec.get("question", "")) and q not in tagset:
                tagset.append(q)
            rec["tags"] = tagset
            rec["answer"] = a
            rec["verified"] = bool(verified) or bool(rec.get("verified"))
            rec["updated_at"] = datetime.now().isoformat(timespec="seconds")
            with db.connect() as conn:
                db._upsert_answer_row(conn, rec)
            return rec

    existing = get_answer(_answer_id(q))
    rec = existing or {
        "id": _answer_id(q),
        "question": q,
        "tags": [],
        "times_used": 0,
        "date_added": datetime.now().date().isoformat(),
    }
    rec["norm"] = _norm(q)
    rec["answer"] = a
    rec["verified"] = bool(verified) or bool(rec.get("verified"))
    rec["source_company"] = source_company or rec.get("source_company", "")
    if tags:
        merged = list(rec.get("tags") or [])
        for t in tags:
            if t and t not in merged:
                merged.append(t)
        rec["tags"] = merged
    rec["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        db._upsert_answer_row(conn, rec)
    return rec


def record_use(answer_id: str) -> dict | None:
    """Bump the reuse counter (called when a banked answer is actually used)."""
    rec = get_answer(answer_id)
    if rec is None:
        return None
    rec["times_used"] = int(rec.get("times_used") or 0) + 1
    rec["last_used"] = datetime.now().date().isoformat()
    with db.connect() as conn:
        db._upsert_answer_row(conn, rec)
    return rec


def delete_answer(answer_id: str) -> bool:
    with db.connect() as conn:
        return conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,)).rowcount > 0


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
# Alternate phrasings for the standard questions, keyed by the stems that
# identify them. Portals word these the same few ways, and some restatements are
# semantic rather than lexical ("in Canada" vs "in the country of employment"),
# which no amount of string similarity will bridge. Seeding them as tags gives
# the bank real recall on day one instead of making the first application of each
# kind pay for a draft. (Encountered phrasings are added the same way, on
# approval — see `save_answer(merge_into=...)`.)
_SEED_TAGS: tuple[tuple[frozenset, tuple[str, ...]], ...] = (
    (frozenset({"authoriz", "work"}), (
        "Are you legally authorised to work in the country of employment?",
        "Do you have the legal right to work in this country?",
        "Are you eligible to work in this country without restriction?",
    )),
    (frozenset({"sponsor"}), (
        "Will you now or in the future require immigration sponsorship?",
        "Do you require visa sponsorship to work in this country?",
        "Will you require a work permit or visa sponsorship for this role?",
    )),
    (frozenset({"relocat"}), (
        "Are you willing to relocate for this position?",
        "Would you consider relocating for this role?",
    )),
    (frozenset({"year", "experi"}), (
        "How many years of relevant experience do you have?",
        "How many years of professional experience do you have?",
    )),
    (frozenset({"remot"}), ("Are you comfortable working remotely?",)),
    (frozenset({"hybrid"}), ("Are you able to work in a hybrid arrangement?",)),
    (frozenset({"driver"}), ("Do you hold a valid driver's license?",)),
)


def _seed_tags_for(question: str) -> list[str]:
    """Alternate phrasings to attach to a seeded question.

    Triggers are matched as substrings of the normalized text rather than against
    stemmed tokens: the stemmer is deliberately crude and doesn't reduce
    "sponsorship" to "sponsor" or "experience" to "experi", so token equality
    would silently miss most of these.
    """
    text = " " + _norm(question) + " "
    tags: list[str] = []
    for triggers, phrasings in _SEED_TAGS:
        if all(t in text for t in triggers):
            tags.extend(p for p in phrasings if _norm(p) != _norm(question))
    return tags


def seed_rows() -> list[dict]:
    """The apply-profile's hand-written `commonAnswers`, as bank records.

    These are the user's own standard answers, so they seed in as **verified**,
    each carrying the alternate phrasings portals are known to use.
    Called once by the DB migration when the `answers` table is empty.
    """
    from .companies import load_apply_profile

    today = datetime.now().date().isoformat()
    out = []
    for question, answer in (load_apply_profile().get("commonAnswers") or {}).items():
        q, a = str(question).strip(), str(answer).strip()
        if not q or not a:
            continue
        out.append({
            "id": _answer_id(q),
            "norm": _norm(q),
            "question": q,
            "answer": a,
            "tags": _seed_tags_for(q),
            "verified": True,
            "times_used": 0,
            "source_company": "",
            "date_added": today,
        })
    return out
