"""Deterministic post-processing to make cover-letter / email prose read like a
real person wrote it. Local models routinely ignore "no em dashes" instructions,
so we strip them mechanically here. We do NOT touch the resume (its date ranges
use an en dash on purpose, and the user is happy with it).

Two passes:
  1. de-dash: replace em/en dashes with natural punctuation (or "to" for ranges).
  2. de-tell: rewrite a few of the most common AI giveaway openers/phrases.
"""

from __future__ import annotations

import re

from .models import ApplicationEmail, CoverLetter, Resume

# Em-style dashes join clauses -> become a comma. En-style/minus mark ranges or
# compounds -> "to" between numbers, a hyphen inside a word.
_EM = "—―‒"   # em dash, horizontal bar, figure dash
_EN = "–−"    # en dash, minus sign


def dedash(text: str) -> str:
    """Remove em/en-style dashes, leaving natural punctuation behind."""
    if not text:
        return text
    t = text
    # numeric range "5–10" / "5 — 10"  ->  "5 to 10"
    t = re.sub(rf"(\d)\s*[{_EM}{_EN}]\s*(\d)", r"\1 to \2", t)
    # em dash = clause join, regardless of surrounding spaces  ->  comma
    t = re.sub(rf"\s*[{_EM}]+\s*", ", ", t)
    # en dash flanked by spaces  ->  comma
    t = re.sub(rf"\s+[{_EN}]+\s+", ", ", t)
    # en dash inside a word ("data–driven")  ->  hyphen (compound)
    t = re.sub(rf"(?<=\w)[{_EN}]+(?=\w)", "-", t)
    # any leftover dashes -> comma
    t = re.sub(rf"[{_EM}{_EN}]+", ", ", t)
    # tidy: no comma pile-ups, no space before comma, no comma before end punct
    t = re.sub(r",\s*,+", ", ", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*([.!?;:])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


_URL_RE = re.compile(r"https?://\S+|www\.\S+|\b[\w.-]+\.(?:com|ca|org|net|io|dev|ai|co)\b/\S*")


def deslash(text: str) -> str:
    """Replace 'a/b' slashes (an AI-ish tell) with natural punctuation. URLs are
    protected; short tokens like N/A, A/B, 24/7 and 'C#/.NET' are left alone."""
    if not text:
        return text
    # Stash URLs so their slashes survive untouched, then restore at the end.
    urls: list[str] = []

    def _stash(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"\x00{len(urls) - 1}\x00"

    t = _URL_RE.sub(_stash, text)
    t = re.sub(r"\s+/\s+", ", ", t)                              # "design / build" -> "design, build"
    t = re.sub(r"(?<=[A-Za-z]{2})/(?=[A-Za-z]{2})", ", ", t)    # "frontend/backend" -> "frontend, backend"
    t = re.sub(r",\s*,+", ", ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: urls[int(m.group(1))], t)
    return t.strip()


# (pattern, replacement) — case-insensitive, applied to cover-letter/email prose.
_TELLS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bI am writing to express my (?:keen |strong )?interest in\b", re.I),
     "I'm applying for"),
    (re.compile(r"\bI am excited to (?:apply|be applying)\b", re.I), "I'd like to apply"),
    (re.compile(r"\bI am confident that my (?:skills and experience|background)\b", re.I),
     "I think my experience"),
    (re.compile(r"\bleverage\b", re.I), "use"),
    (re.compile(r"\bleveraging\b", re.I), "using"),
    (re.compile(r"\bpassionate about\b", re.I), "genuinely interested in"),
    (re.compile(r"\bin today's fast-paced (?:world|environment|industry)\b", re.I), ""),
    (re.compile(r"\bseamlessly\b", re.I), "smoothly"),
    (re.compile(r"\bseamless\b", re.I), "smooth"),
    (re.compile(r"\bstreamline\b", re.I), "simplify"),
    (re.compile(r"\bstreamlining\b", re.I), "simplifying"),
    (re.compile(r"\bthrive in (?:a )?(?:dynamic|fast-paced)\s+(?:environments?|settings?)\b", re.I),
     "work well in busy settings"),
    (re.compile(r"\bthrive\b", re.I), "do well"),
    (re.compile(r"\bdynamic environments?\b", re.I), "busy settings"),
    (re.compile(r"\bdetail-oriented\b", re.I), "careful"),
]


def detell(text: str) -> str:
    """Soften the most common AI giveaway phrases. Conservative on purpose."""
    if not text:
        return text
    t = text
    for pat, repl in _TELLS:
        t = pat.sub(repl, t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    return t.strip()


def _clean(text: str) -> str:
    return detell(deslash(dedash(text)))


def _clean_multiline(text: str) -> str:
    """Like _clean, but preserves paragraph/line structure. The single-line
    passes collapse every newline (\\s{2,} -> ' '), which would flatten an email
    into one blob, so clean each line on its own and rejoin."""
    if not text:
        return text
    lines = [(_clean(ln) if ln.strip() else "") for ln in text.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()  # collapse runs of blank lines


def humanize_cover_letter(cl: CoverLetter) -> CoverLetter:
    cl.contactLine = dedash(cl.contactLine)
    cl.greeting = _clean(cl.greeting)
    cl.body = [_clean(p) for p in cl.body]
    cl.signOff = _clean(cl.signOff)
    cl.signature = dedash(cl.signature)
    return cl


def humanize_email(email: ApplicationEmail) -> ApplicationEmail:
    email.subject = deslash(dedash(email.subject))
    email.body = _clean_multiline(email.body)
    return email


def humanize_resume(resume: Resume) -> Resume:
    """Strip em/en dashes and slashes from the résumé's prose. Run AFTER the
    truth-guard so grounding/validation is already done — this only cleans wording,
    it never adds facts."""
    if resume.summary:
        resume.summary = _clean(resume.summary)
    if resume.headline:
        resume.headline = deslash(dedash(resume.headline))
    resume.skills = [deslash(dedash(s)) for s in (resume.skills or [])]
    for e in resume.experience or []:
        e.bullets = [deslash(dedash(b)) for b in (e.bullets or [])]
    resume.certifications = [deslash(dedash(c)) for c in (resume.certifications or [])]
    return resume


def humanize_answer(text: str) -> str:
    """Clean a screening-question answer: strip em/en dashes and AI-tell phrases.
    Local models keep emitting them no matter what the prompt says."""
    return _clean(text)
