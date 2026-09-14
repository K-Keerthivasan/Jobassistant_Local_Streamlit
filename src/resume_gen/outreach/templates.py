"""Render an outreach template (data/outreach-templates.json) for one job + contact.

Variables are ``{{name}}`` or ``{{name|fallback}}``. Everything is resolved here,
before anything reaches n8n. The rules baked into the file are enforced at
render time, not trusted: subject under 60 characters, body under 150 words, no
em or en dashes, never a sponsorship or immigration word except in the pathway
template, and the fit sentence must be the evidence-traced one from the grade.
"""

from __future__ import annotations

import re
from datetime import date

from .. import lanes as lane_data

_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*(?:\|\s*([^}]*))?\}\}")


class TemplateError(ValueError):
    pass


def get_template(template_id: str) -> dict:
    data = lane_data.load_outreach_templates()
    for t in data.get("templates", []):
        if t.get("id") == template_id:
            return t
    raise TemplateError(f"unknown outreach template {template_id!r}")


def rules() -> dict:
    return lane_data.load_outreach_templates().get("rules", {})


def _signature_links(job: dict | None) -> str:
    lane = lane_data.get_lane((job or {}).get("lane_slug") or "") if job else None
    links = lane_data.portfolio_links_for(lane)
    shown = [re.sub(r"^https?://", "", l.url).rstrip("/") for l in links]
    return " | ".join(shown)


def variables(job: dict | None, contact: dict, *, applied_on: str = "") -> dict:
    prof = lane_data.load_profile_data()
    job = job or {}
    grade = job.get("grade") or {}
    lane = lane_data.get_lane(job.get("lane_slug") or "") if job.get("lane_slug") else None
    name = prof.get("name", "")
    first, _, last = name.partition(" ")
    hr_name = (contact.get("hr_name") or "").strip()
    v = {
        "company": contact.get("company") or job.get("company", ""),
        "title": job.get("title", ""), "location": job.get("location", ""),
        "lane": job.get("lane_slug", ""), "lane_title": (lane.title if lane else job.get("lane", "")) or "this area",
        "pathway_tag": (f"{job.get('pathway_type')}: {job.get('pathway_detail')}" if job.get("pathway_type") else ""),
        "pathway_type": job.get("pathway_type", ""), "pathway_detail": job.get("pathway_detail", ""),
        "noc": job.get("noc", ""), "apply_url": job.get("apply_url", ""), "posted": job.get("posted", ""),
        "tier": grade.get("tier", ""), "gap_flags": grade.get("gap_flags_text", ""),
        "fit_sentence": grade.get("fit_sentence", ""), "years_line": (job.get("fit") or {}).get("years_line", ""),
        "name": name, "known_as": prof.get("known_as", first), "first_name": first, "last_name": last,
        "city": (prof.get("location") or {}).get("city", ""), "province": (prof.get("location") or {}).get("province", ""),
        "hr_name": hr_name, "hr_first_name": hr_name.split(" ")[0] if hr_name else "",
        "hr_email": contact.get("hr_email", ""),
        "applied_on": applied_on or job.get("date_sent") or job.get("sent_at", "")[:10] or date.today().isoformat(),
        "today": date.today().isoformat(),
        "signature_links": _signature_links(job),
    }
    for k, val in (prof.get("portfolio") or {}).items():
        v[f"portfolio.{k}"] = val
    return v


def _fill(text: str, v: dict) -> tuple[str, list[str]]:
    missing: list[str] = []

    def rep(m):
        key, fallback = m.group(1), m.group(2)
        val = v.get(key, "")
        if val in ("", None):
            if fallback is not None:
                return fallback
            missing.append(key)
            return ""
        return str(val)
    return _VAR.sub(rep, text), missing


def _clean(text: str) -> str:
    t = re.sub(r"\s*[–—]\s*", ", ", text or "")
    t = re.sub(r"[ \t]{2,}", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def render(template_id: str, job: dict | None, contact: dict, *, applied_on: str = "") -> dict:
    """Returns {subject, body, template_id, variables_used, warnings}. Raises
    TemplateError when a rule is broken, so a malformed message never reaches the
    queue."""
    t = get_template(template_id)
    r = rules()
    v = variables(job, contact, applied_on=applied_on)
    subject, miss_s = _fill(t.get("subject", ""), v)
    body, miss_b = _fill(t.get("body", ""), v)
    subject, body = _clean(subject), _clean(body)
    missing = sorted(set(miss_s + miss_b))
    if "fit_sentence" in missing:
        raise TemplateError("this template needs an evidence-traced fit sentence and the job has none; grade the job first")
    if missing:
        raise TemplateError(f"unresolved variables: {', '.join(missing)}")
    if len(subject) > r.get("subject_max_chars", 60):
        raise TemplateError(f"subject is {len(subject)} characters; limit is {r.get('subject_max_chars', 60)}")
    words = len(body.split())
    if words > r.get("body_max_words", 150):
        raise TemplateError(f"body is {words} words; limit is {r.get('body_max_words', 150)}")
    low = body.lower() + " " + subject.lower()
    allowed = set(r.get("immigration_pathway_allowed_in", []))
    for w in r.get("never_mention", []):
        if w.lower() in low and template_id not in allowed:
            raise TemplateError(f"message mentions '{w}', which is never allowed in this template")
    if re.search(r"[–—]", subject + body):
        raise TemplateError("message contains an em or en dash")
    return {"subject": subject, "body": body, "template_id": template_id,
            "attach_resume": bool(t.get("attach_resume")), "allowed_for_pattern_guess": bool(t.get("allowed_for_pattern_guess", True)),
            "sequence": t.get("sequence") or [], "variables_used": {k: v[k] for k in v if f"{{{{{k}" in t.get("body", "") + t.get("subject", "")},
            "word_count": words}
