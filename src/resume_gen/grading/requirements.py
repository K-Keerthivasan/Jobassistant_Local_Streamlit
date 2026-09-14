"""Split a posting body into hard requirements, nice-to-haves and everything else.

Deterministic, no model call. The signals (brief section 4, step 1):

    hard   "required", "must have", "minimum", "essential", "need", a line under a
           Requirements / Qualifications / What you bring heading
    nice   "asset", "preferred", "nice to have", "bonus", "a plus", "ideally",
           a line under a Nice to have / Assets / Preferred heading

Lines that sit under a Responsibilities / About heading are context: they are
matched for evidence but never raise a gap flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HARD_HEAD = re.compile(
    r"^\W*(?:(?:minimum|basic|required|key|core|essential|technical)\s+)?"
    r"(?:requirements?|qualifications?|must[- ]haves?|what you(?:'ll)? (?:bring|need|have)|"
    r"what we(?:'re| are) looking for|who you are|skills? (?:and|&) (?:experience|qualifications)|"
    r"experience (?:and|&) skills|you have|you bring|the ideal candidate|"
    r"required (?:skills|experience|qualifications)|skills required|knowledge, skills and abilities)\W*$",
    re.I)
_NICE_HEAD = re.compile(
    r"^\W*(?:nice[- ]to[- ]haves?|assets?|preferred(?: qualifications| skills)?|bonus(?: points)?|"
    r"it(?:'s| is| would be) (?:a plus|great|nice) if|desirable|good to have|"
    r"additional (?:skills|qualifications)|considered an asset|what would set you apart|"
    r"preferred but not required)\W*$", re.I)
_CONTEXT_HEAD = re.compile(
    r"^\W*(?:responsibilities|duties|what you(?:'ll)? (?:do|be doing|work on)|about (?:the role|us|the company|the team)|"
    r"the role|the opportunity|role overview|job (?:summary|description|overview)|key (?:responsibilities|duties)|"
    r"your (?:role|responsibilities|impact|day)|a day in the life|what we offer|benefits|perks|compensation|"
    r"why join|about you|the team|company overview|how to apply|equal opportunity)\W*$", re.I)

_NICE_INLINE = re.compile(
    r"\b(?:nice[- ]to[- ]have|an? (?:strong )?asset|assets?\b|preferred|bonus|a plus|is a plus|ideally|"
    r"would be (?:an? )?(?:advantage|great|nice|beneficial)|not required|optional|desirable|good to have|"
    r"familiarity with .* (?:is|would be) (?:a plus|an asset))\b", re.I)
_HARD_INLINE = re.compile(
    r"\b(?:required|must[- ]have|must be|minimum|at least|essential|mandatory|need to|needs to|"
    r"proficien(?:t|cy) (?:in|with)|strong (?:knowledge|experience|skills|understanding) (?:of|in|with)|"
    r"(?:solid|demonstrated|proven|hands-on) experience (?:with|in)|\d+\+? ?years?)\b", re.I)


@dataclass
class Requirements:
    hard: list[str] = field(default_factory=list)
    nice: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    def all_text(self) -> str:
        return "\n".join([*self.hard, *self.nice, *self.context])


def _lines(description: str) -> list[str]:
    text = (description or "").replace("\r\n", "\n")
    # The importer restores ' | ' to newlines; a pasted body may still carry them.
    text = re.sub(r"\s\|\s", "\n", text)
    out: list[str] = []
    for raw in text.split("\n"):
        ln = raw.strip().lstrip("-*•·▪–— ").strip()
        if not ln:
            continue
        # long paragraphs: split into sentences so one clause does not decide the lot
        if len(ln) > 220:
            out.extend(s.strip() for s in re.split(r"(?<=[.;!?])\s+", ln) if s.strip())
        else:
            out.append(ln)
    return out


def extract_requirements(description: str) -> Requirements:
    req = Requirements()
    mode = "context"
    for ln in _lines(description):
        short = len(ln) <= 80 and not ln.endswith(".")
        if short and _NICE_HEAD.match(ln):
            mode = "nice"; continue
        if short and _HARD_HEAD.match(ln):
            mode = "hard"; continue
        if short and _CONTEXT_HEAD.match(ln):
            mode = "context"; continue
        if _NICE_INLINE.search(ln):
            req.nice.append(ln)
        elif mode == "hard":
            req.hard.append(ln)
        elif _HARD_INLINE.search(ln) and mode != "nice":
            req.hard.append(ln)
        elif mode == "nice":
            req.nice.append(ln)
        else:
            req.context.append(ln)
    return req
