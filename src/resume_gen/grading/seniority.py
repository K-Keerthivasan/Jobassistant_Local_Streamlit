"""Seniority guard (brief section 4). Applied on import, shown as a warning,
never a filter.

    band 0 to 3 years
    a stated minimum of 4 passes only as a range with a floor of 2 or lower
    a flat "4+" or anything 5 and above fails; "3 to 5" fails
    title words Senior, Sr., Staff, Principal, Lead, Architect, Manager, Head of,
    Director, II, III trigger a body check and pass only where the body states
    3 years or lower explicitly
"""

from __future__ import annotations

import re

_TITLE_WORDS = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|architect|manager|head of|director|ii|iii|"
    r"specialist iii|analyst iii|engineer iii)\b", re.I)
_RANGE = re.compile(r"\b(\d{1,2})\s*(?:\+\s*)?(?:-|to|–|—|/)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
_PLUS = re.compile(r"\b(\d{1,2})\s*(?:\+|plus|or more)\s*(?:years?|yrs?)\b", re.I)
_MIN = re.compile(r"\b(?:minimum(?: of)?|at least|min\.?|over|more than)\s*(\d{1,2})\s*(?:years?|yrs?)\b", re.I)
_BARE = re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)(?:\s+of)?\s+(?:[\w/-]+\s+){0,4}?(?:experience|exp\b|in\b|with\b|working)", re.I)
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10}
_WORD_YEARS = re.compile(r"\b(one|two|three|four|five|six|seven|eight|ten)\s*(\+|plus|or more)?\s*(?:years?|yrs?)\b", re.I)


def find_years(text: str) -> list[dict]:
    """Every years-of-experience figure in the text, as {lo, hi, flat_plus, quote}."""
    out = []
    t = text or ""
    for m in _RANGE.finditer(t):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi <= 30:
            out.append({"lo": lo, "hi": hi, "flat_plus": False, "quote": m.group(0)})
    covered = [(m.start(), m.end()) for m in _RANGE.finditer(t)]

    def _free(m):
        return not any(s <= m.start() < e for s, e in covered)

    for m in _PLUS.finditer(t):
        if _free(m):
            n = int(m.group(1))
            out.append({"lo": n, "hi": None, "flat_plus": True, "quote": m.group(0)})
    for m in _MIN.finditer(t):
        if _free(m):
            n = int(m.group(1))
            out.append({"lo": n, "hi": None, "flat_plus": True, "quote": m.group(0)})
    for m in _WORD_YEARS.finditer(t):
        n = _WORD_NUM[m.group(1).lower()]
        out.append({"lo": n, "hi": None if m.group(2) else n, "flat_plus": bool(m.group(2)), "quote": m.group(0)})
    for m in _BARE.finditer(t):
        if _free(m) and not any(m.group(0).startswith(o["quote"]) for o in out):
            n = int(m.group(1))
            out.append({"lo": n, "hi": n, "flat_plus": False, "quote": m.group(0)})
    return out


def _figure_passes(f: dict) -> bool:
    lo, hi = f["lo"], f["hi"]
    if f["flat_plus"] or hi is None:
        return lo <= 3
    if hi <= 3:
        return True
    return lo <= 2 and hi <= 5


def check_seniority(title: str, description: str, years_line: str = "") -> dict:
    """Returns {warning, pass, reason, figures, title_flag, years_line}."""
    title_hit = _TITLE_WORDS.search(title or "")
    # The fit report's quoted years line is the most trustworthy figure; the body is next.
    figures = find_years(years_line) or find_years(description)
    strictest = None
    for f in figures:
        if strictest is None or f["lo"] > strictest["lo"] or (f["lo"] == strictest["lo"] and (f["hi"] or 99) > (strictest["hi"] or 99)):
            strictest = f
    result = {"title_flag": title_hit.group(0) if title_hit else "", "figures": figures,
              "years_line": years_line or "", "pass": True, "warning": False, "reason": ""}
    if strictest is not None and not _figure_passes(strictest):
        result.update(pass_=False)
        result["pass"] = False
        result["reason"] = f"asks for {strictest['quote'].strip()}; band is 0 to 3 years"
    if title_hit:
        explicit_ok = any(f["hi"] is not None and f["hi"] <= 3 and not f["flat_plus"] for f in figures) or \
                      any(f["hi"] is None and f["lo"] <= 3 and not f["flat_plus"] for f in figures)
        if not figures:
            result["pass"] = False
            result["reason"] = f"title word '{title_hit.group(0)}' and no years figure stated"
        elif not explicit_ok and result["pass"]:
            result["pass"] = False
            result["reason"] = f"title word '{title_hit.group(0)}' without an explicit figure of 3 years or lower"
    result.pop("pass_", None)
    result["warning"] = not result["pass"]
    return result
