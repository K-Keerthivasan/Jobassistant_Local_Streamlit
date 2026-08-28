"""Apply straight against the local database — no HTTP, no container.

The app is local, so an assistant driving a browser on this machine has no reason
to round-trip through ``:8088`` to reach data sitting in ``data/resume.db``. This
CLI runs the same orchestration the API exposes (``automation.autoapply``) in
process: the answers bank, the form library, the truth guard, the sensitive-
question rule and the confirmation gate all still apply — only the transport is
gone.

It also prints **compact text instead of JSON**. Over a hundred applications the
difference in an assistant's context budget is substantial, and a fill plan reads
better as a table than as a response body.

Typical loop, one job at a time::

    python -m resume_gen.automation.apply_cli next
    python -m resume_gen.automation.apply_cli prepare <job_key> --fields form.json
    # ...fill the browser from the printed plan, user reviews and submits...
    python -m resume_gen.automation.apply_cli done <session_id>
    python -m resume_gen.automation.apply_cli blocked <session_id> --reason "login wall"

``status`` shows progress; ``show`` re-prints a prepared plan.

The final Submit is never clicked here: ``done`` records an application the user
already submitted themselves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from . import autoapply
from ..intake import apply_sessions, form_templates, store

app = typer.Typer(add_completion=False, help="Apply to jobs against the local DB.")


def _out(line: str = "") -> None:
    print(line)


# --------------------------------------------------------------------------- #
@app.command("next")
def next_job(
    limit: int = typer.Option(5, help="How many upcoming jobs to list."),
    company: str = typer.Option("", help="Only this employer."),
    since: str = typer.Option("", help="Only jobs found on/after YYYY-MM-DD."),
    real_only: bool = typer.Option(
        True, "--real-only/--all",
        help="Only jobs whose apply URL is a real employer/ATS page (default), "
             "rather than a LinkedIn/Indeed/Job Bank listing with no form on it.",
    ),
):
    """The next jobs to apply to. Attempted ones drop off, so this resumes itself."""
    rows = autoapply.candidates(limit=500, company=company, since=since)
    if real_only:
        rows = [r for r in rows if not _is_listing(r["apply_url"])]
    if not rows:
        _out("Nothing left to apply to." + ("" if real_only else " (queue empty)"))
        raise typer.Exit(0)

    _out(f"{len(rows)} ready" + (f" (showing {min(limit, len(rows))})" if len(rows) > limit else ""))
    for r in rows[:limit]:
        tmpl = form_templates.get_for_url(r["apply_url"])
        marks = []
        if r["repeat_company"]:
            marks.append("repeat")
        if tmpl:
            marks.append(f"form known x{tmpl.get('times_used', 0)}")
        if r["likely_blocked"]:
            marks.append("BLOCKED")
        _out(f"  {r['key_id']}  {r['company'][:22]:<24}{r['title'][:34]:<36}"
             f"{r['ats']:<10}{' · '.join(marks)}")
        _out(f"      {r['apply_url']}")


_LISTING_HOSTS = ("linkedin.com", "indeed.com", "jobbank.gc.ca", "glassdoor.")


def _is_listing(url: str) -> bool:
    """True for aggregator listing pages, which have no application form on them."""
    return any(h in (url or "").lower() for h in _LISTING_HOSTS)


@app.command()
def prepare(
    job_key: str = typer.Argument(..., help="key_id from `next`."),
    fields: Path = typer.Option(None, "--fields", help="JSON file: the form controls "
                                "read off the page. Omit to reuse the remembered form."),
    url: str = typer.Option("", help="Override the apply URL (after a redirect)."),
    regenerate: bool = typer.Option(False, "--regenerate", help="Force a fresh résumé."),
):
    """Plan an application: documents, field values, answers. Submits nothing."""
    job = store.get_job(job_key)
    if job is None:
        _out(f"No job {job_key!r}. Run `next` for valid keys.")
        raise typer.Exit(1)

    target_url = url or job.apply_url
    spec: list[dict] = []
    if fields:
        spec = json.loads(Path(fields).read_text(encoding="utf-8"))
        if isinstance(spec, dict):
            spec = spec.get("fields", [])
    else:
        tmpl = form_templates.get_for_url(target_url)
        if not tmpl:
            _out("No remembered form for this site — read the page and pass --fields.")
            raise typer.Exit(2)
        spec = tmpl["fields"]
        _out(f"Using remembered form ({tmpl['field_count']} fields, "
             f"seen {tmpl.get('times_used', 0)}x). Verify the selectors still exist.")

    session = autoapply.prepare(
        job_url=target_url, company=job.company, title=job.title,
        description="",                     # already stored on the job
        location=job.location, fields=spec, regenerate=regenerate,
    )
    _print_plan(session)


def _print_plan(session: dict) -> None:
    s = session["summary"]
    r = session.get("review") or {}
    _out("")
    _out(f"session {session['session_id']}   {s['job']['company']} — {s['job']['title']}")
    if session.get("reused_run"):
        _out(f"  documents: reusing the application generated for this job ({session['run_id']})")
    for kind, doc in (s.get("documents") or {}).items():
        where = doc.get("rel_path") or doc.get("url") or doc.get("error")
        _out(f"  {kind:<13} {where}")

    _out("")
    for f in s.get("standard_fields", []):
        _out(f"  FILL   {str(f['label'])[:44]:<46} {str(f['value'])[:40]}")
    for a in s.get("answers_reused", []):
        _out(f"  REUSE  {a['question'][:44]:<46} {a['answer'][:40]}")
    for a in s.get("answers_from_profile", []):
        _out(f"  PROFILE{a['question'][:44]:<46} {a['answer'][:40]}")
    for a in s.get("answers_new", []):
        _out(f"  NEW    {a['question']}")
        _out(f"         {a['answer']}")
    for a in s.get("answers_for_you", []):
        _out(f"  YOURS  {a['question'][:60]}   ({a['why']})")
    for f in s.get("left_blank", []):
        req = "REQUIRED " if f.get("required") else ""
        _out(f"  BLANK  {req}{str(f['label'])[:50]}  — {f.get('reason', '')}")

    _out("")
    if r.get("clean"):
        _out("  CLEAN — everything came from your profile or approved answers.")
    else:
        for reason in r.get("needs_review", []):
            _out(f"  CHECK  {reason}")
    _out("")
    _out(f"  next: apply_cli done {session['session_id']}   (after you submit)")


@app.command()
def show(session_id: str = typer.Argument(...)):
    """Re-print a prepared plan."""
    session = apply_sessions.get_session(session_id)
    if session is None:
        _out(f"No session {session_id!r}.")
        raise typer.Exit(1)
    session["review"] = autoapply.review_flags(session)
    session["summary"] = autoapply.build_summary(session)
    _print_plan(session)


@app.command()
def done(
    session_id: str = typer.Argument(...),
    edit: list[str] = typer.Option(None, "--edit", help="selector=corrected text "
                                   "(repeatable). The corrected text is what gets banked."),
    note: str = typer.Option("", help="Anything worth remembering about this one."),
):
    """Record an application **you** submitted: banks the answers, marks it applied."""
    edits = {}
    for item in edit or []:
        key, _, value = item.partition("=")
        if key and value:
            edits[key.strip()] = value.strip()

    res = autoapply.confirm(session_id, approved=True, submit_by="me",
                            edits=edits or None, note=note)
    out = autoapply.log_outcome(session_id, status="submitted", submitted_by="me",
                                note=note or "submitted by the user")
    job = store.get_job(out["job_key"])
    _out(f"applied: {job.company} — {job.title}")
    _out(f"  status={job.status}  applied={job.applied}")
    _out(f"  {res['note']}")


@app.command()
def skip(session_id: str = typer.Argument(...), note: str = typer.Option("", help="Why.")):
    """Decline this application. Nothing is banked; the attempt is still logged."""
    autoapply.confirm(session_id, approved=False, note=note)
    _out(f"skipped, logged. {note}")


@app.command()
def blocked(
    session_id: str = typer.Argument(...),
    reason: str = typer.Option(..., help="CAPTCHA / login wall / posting closed / broken form."),
):
    """Log a job that couldn't be applied to, so the batch moves on."""
    autoapply.log_outcome(session_id, status="failed", note=reason)
    _out(f"blocked, logged: {reason}")


@app.command()
def status():
    """Progress: attempts by outcome, what's left, and what's been learned."""
    counts: dict[str, int] = {}
    for s in apply_sessions.list_sessions(limit=2000):
        counts[s.get("status", "?")] = counts.get(s.get("status", "?"), 0) + 1
    rows = autoapply.candidates(limit=10000)
    real = [r for r in rows if not _is_listing(r["apply_url"])]

    from ..intake import answers as bank

    _out("attempts: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none yet"))
    _out(f"remaining: {len(real)} on employer/ATS sites, "
         f"{len(rows) - len(real)} on listing sites with no form")
    _out(f"learned:   {len(bank.list_answers())} banked answers, "
         f"{len(form_templates.list_templates())} remembered forms")


if __name__ == "__main__":
    app()
