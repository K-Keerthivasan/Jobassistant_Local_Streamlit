"""Semi-automated job applications: prepare -> confirm -> submit -> log.

This is the orchestration layer behind the ``/apply/*`` endpoints. It owns the
*decisions* (what goes in each field, which answers are reused, what the user is
shown before submitting); it does **not** drive a browser. The caller supplies
the form it read off the page and performs the typing/clicking, which is what
keeps the feature ATS-agnostic: any driver that can describe a form and fill it
— the Playwright MCP server, an in-process Playwright script, anything else —
works against the same three calls.

The flow, and the guarantees at each step:

``prepare(...)``
    Resolve/queue the job, generate a tailored résumé + cover letter through the
    normal pipeline, answer every screening question (bank first, draft second),
    map the standard fields from the apply-profile, and return a fill plan plus a
    human-readable summary. Nothing is submitted. Nothing is banked yet.

``confirm(...)``
    Records the user's decision. **Only** on approval do newly drafted answers
    enter the bank, so a rejected application never teaches it anything. Returns
    whether submission may proceed — the single gate every caller must respect.

``log_outcome(...)``
    Writes the result to the existing review-queue job (status, applied flag,
    apply_log entry). Called for every terminal state, including rejection and
    failure, so the tracker never silently loses an attempt.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from ..config import settings
from ..intake import answers as answers_bank
from ..intake import apply_sessions
from ..intake import runs as runs_store
from ..intake import store
from ..intake.models import JobPosting, QueuedJob
from ..models import TargetRole
from .playwright_apply import detect_ats

# --------------------------------------------------------------------------- #
# Standard-field mapping
#
# Maps a form field to a key in data/apply_profile.json by matching the field's
# label/name against known phrasings. Longest phrase wins, so "first name" beats
# the bare "name". This is intentionally a table and not per-ATS code: every
# portal words these the same handful of ways.
# --------------------------------------------------------------------------- #
# Plain labelled inputs: "First Name", "City". These are *identity* data and are
# filled straight from the apply-profile.
IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "firstName": ("first name", "given name", "forename", "firstname"),
    "lastName": ("last name", "family name", "surname", "lastname"),
    "fullName": ("full name", "legal name", "your name", "candidate name", "name"),
    "email": ("email address", "e mail address", "email", "e mail"),
    "phone": ("phone number", "mobile number", "telephone", "cell phone",
              "contact number", "phone", "mobile"),
    "address": ("street address", "address line 1", "mailing address", "address"),
    "city": ("city", "town", "municipality"),
    "province": ("province", "state", "region", "province or state"),
    "country": ("country", "country of residence"),
    "postalCode": ("postal code", "zip code", "zipcode", "postcode", "zip"),
    "linkedin": ("linkedin profile", "linkedin url", "linkedin"),
    "portfolio": ("portfolio", "personal website", "website", "web site"),
    "github": ("github profile", "github url", "github", "git hub"),
}

# Questions whose answer the profile already knows. These are asked as questions
# ("Are you legally authorized to work…?"), so they go down the screening path —
# but they never need a drafted answer, because the profile has the fact.
QUESTION_FIELDS: dict[str, tuple[str, ...]] = {
    "workAuthorization": ("legally authorized to work", "authorized to work",
                          "work authorization", "eligible to work",
                          "right to work", "legally eligible", "legally entitled"),
    "requiresSponsorship": ("require sponsorship", "visa sponsorship",
                            "need sponsorship", "immigration sponsorship",
                            "sponsorship"),
    "experienceYears": ("years of experience", "total experience",
                        "years experience", "experience level"),
    "education": ("highest level of education", "highest degree",
                  "level of education", "highest qualification"),
    "salaryExpectation": ("salary expectation", "expected salary",
                          "desired salary", "compensation expectation",
                          "expected compensation", "desired compensation",
                          "salary requirement"),
    "availableStartDate": ("start date", "available to start", "availability",
                           "when can you start", "earliest start"),
    "noticePeriod": ("notice period", "period of notice"),
}

# A label starting with one of these (or ending in "?") is a question, not a
# field label. The distinction matters: without it, "Are you legally authorized
# to work in the country of employment?" matches the `country` profile key on the
# word "country" and gets filled with "Canada" instead of "Yes".
_INTERROGATIVES = (
    "are ", "is ", "do ", "does ", "did ", "have ", "has ", "will ", "would ",
    "can ", "could ", "should ", "what ", "why ", "how ", "when ", "where ",
    "which ", "who ", "please ", "describe ", "tell ", "in your own words",
)


# Questions no model may answer. Two kinds, both hard "leave it to the human":
#
#   * protected characteristics (EEO/self-identification) — gender, race, veteran
#     and disability status, date of birth, national ID numbers. These are the
#     candidate's to disclose or decline, always optional by law, and an invented
#     answer is both a fabrication and a legal problem.
#   * attestations and consents — certifying accuracy, e-signatures, agreeing to
#     terms, marketing opt-ins. An agent cannot consent on someone's behalf.
#
# Enforced here, in the server, rather than in a browser driver, so it holds for
# every caller. Matched against the raw label (not `_norm`) so the spelling
# normalisation can't mangle a term.
_SENSITIVE = re.compile(
    r"(gender|sex assigned|sexual orientation|pronoun|race|racial|ethnic|"
    r"disabilit|veteran|military status|indigenous|aboriginal|first nations|"
    r"religio|marital status|date of birth|birth ?date|\bage\b|"
    r"social insurance|social security|\bssn\b|\bsin\b|driver'?s? licence number|"
    r"self.identif|equal opportunity|\beeo\b|accommodation needs|"
    r"certif(y|ication) that|electronic signature|e.signature|\bsignature\b|"
    r"agree to (the )?(terms|privacy)|terms and conditions|privacy (policy|consent)|"
    r"consent to|marketing|text message|\bsms\b|talent (pool|community))",
    re.I,
)


def is_sensitive(question: str) -> bool:
    """True if this question must be answered by the human, never drafted."""
    return bool(_SENSITIVE.search(question or ""))


def _norm(text: str) -> str:
    t = (text or "").lower()
    # British -> American spelling, so "authorised" matches "authorized".
    t = t.replace("ise", "ize").replace("isa", "iza")
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_question(field: dict) -> bool:
    """True if this form control asks something rather than labelling a value."""
    label = (field.get("label") or "").strip()
    if not label:
        return False
    if label.endswith("?"):
        return True
    low = _norm(label) + " "
    return low.startswith(_INTERROGATIVES) or (field.get("type") or "") == "textarea"


def match_profile_key(field: dict, table: dict[str, tuple[str, ...]] | None = None
                      ) -> tuple[str, str]:
    """Best (profile_key, matched_phrase) for a form field, or ("", "").

    Looks at the field's label first (what a human reads), then its name/id
    attribute (what the DOM calls it) — the label is the more reliable signal
    when a portal's markup uses opaque ids. Longest matching phrase wins, so
    "first name" beats the bare "name".
    """
    table = IDENTITY_FIELDS if table is None else table
    haystacks = [
        _norm(field.get("label") or field.get("question") or ""),
        _norm(f"{field.get('name') or ''} {field.get('id') or ''} "
              f"{field.get('placeholder') or ''}"),
    ]
    best_key, best_phrase = "", ""
    for hay in haystacks:
        if not hay:
            continue
        for key, phrases in table.items():
            for phrase in phrases:
                if phrase in hay and len(phrase) > len(best_phrase):
                    best_key, best_phrase = key, phrase
        if best_key:            # label matched — don't let the name attribute override it
            break
    return best_key, best_phrase


def _snap_to_option(value: str, options: list[str]) -> tuple[str, bool]:
    """Coerce an answer onto one of a select/radio field's real options.

    Returns (value, snapped). A drafted sentence is useless in a dropdown, so we
    pick the closest option; if nothing is close the original is returned and the
    caller flags the field for manual attention rather than guessing.
    """
    if not options:
        return value, False
    v = _norm(value)
    for opt in options:                      # exact / contained match first
        if _norm(opt) == v:
            return opt, False
    best, best_score = "", 0.0
    for opt in options:
        s = answers_bank.score(value, opt)
        if s > best_score:
            best, best_score = opt, s
    if best_score >= 0.6:
        return best, True
    return value, False


# --------------------------------------------------------------------------- #
# Job resolution — reuse the existing review queue, never a second tracker
# --------------------------------------------------------------------------- #
def _norm_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    return u.split("?")[0].lower()


def resolve_job(*, job_url: str, company: str = "", title: str = "",
                description: str = "", location: str = "",
                contact_email: str = "") -> QueuedJob:
    """Find this posting in the review queue, or add it.

    Matching on the apply URL first means a job already queued by intake (Job
    Bank, an ATS source, the browser saver) is *reused* — the application is
    tracked against the row you already know about instead of a duplicate.
    """
    target = _norm_url(job_url)
    if target:
        for q in store.list_queue():
            if _norm_url(q.apply_url) == target:
                # Backfill anything the queue was missing but the page gave us.
                patch = {k: v for k, v in (
                    ("description", description), ("location", location),
                    ("contact_email", contact_email), ("company", company),
                    ("title", title),
                ) if v and not (getattr(q, k, "") or "").strip()}
                if patch:
                    updated = store.update_fields(q.key_id, patch)
                    if updated is not None:
                        return updated
                return q

    posting = JobPosting(
        source="autoapply",
        source_company=urlsplit(job_url).netloc if job_url else "",
        job_id=job_url,
        company=company,
        title=title,
        location=location,
        description=description,
        apply_url=job_url,
        contact_email=contact_email,
    )
    existing = store.get_job(posting.key)
    if existing is not None:
        return existing
    return store.commit([posting])[0]


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def materialize_documents(run_id: str, dest_dir: str | Path | None = None) -> dict:
    """Render this run's résumé + cover-letter PDFs to real files for upload.

    Generated applications live in the database, not on disk (see
    ``render/ondemand.py``), so an upload needs them written out first.

    Three locations come back per document, because the writer and the browser
    are often not the same machine:

    ``rel_path``
        Path relative to the project root — **use this one**. The output dir lives
        under ``data/``, which is bind-mounted into the container, so the file the
        API just wrote is genuinely on the host's disk; only the absolute path
        differs. Resolving ``rel_path`` against the repo root works from either
        side, which an absolute container path never does.
    ``path``
        Absolute, as seen by whoever rendered it. Correct when the API runs on the
        host; a ``/app/...`` path that doesn't exist on Windows when it's in Docker.
    ``url``
        ``/download/...`` — the always-correct fallback: fetch it over HTTP.
    """
    bundle = runs_store.get_run(run_id)
    if bundle is None:
        raise ValueError(f"No generated application found for run {run_id!r}.")

    from ..config import ROOT
    from ..render.ondemand import render_artifact

    # Default inside the project, not the system temp dir: the Playwright MCP
    # server restricts file access to its workspace roots, so a PDF written to
    # %TEMP% can't be attached to an upload control. Gitignored.
    out_dir = Path(dest_dir) if dest_dir else (
        ROOT / "data" / "job-applications" / "outbox"
        / re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id)[:60]
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    docs: dict[str, dict] = {}
    for kind, artifact in (("resume", "resume.pdf"), ("cover_letter", "cover.pdf")):
        entry = {"url": f"/download/{run_id}/{artifact}", "path": "",
                 "rel_path": "", "error": ""}
        try:
            data, filename, _mime = render_artifact(bundle, artifact)
            path = out_dir / filename
            path.write_bytes(data)
            entry["path"] = str(path)
            try:
                # Posix-style so it pastes cleanly into a tool call on any host.
                entry["rel_path"] = path.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                entry["rel_path"] = ""     # a custom dest_dir outside the repo
        except Exception as e:
            # A cover letter can legitimately be absent; a résumé failure is worth
            # surfacing, but not worth sinking the whole preparation over — the
            # summary shows the error and the user decides.
            entry["error"] = str(e)
        docs[kind] = entry
    return docs


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def plan_standard_fields(fields: list[dict], profile: dict
                         ) -> tuple[list[dict], list[dict], list[dict]]:
    """Sort the extracted form into (fillable, questions, unfilled).

    * **fillable** — a plain labelled input the apply-profile has a value for.
    * **questions** — anything question-shaped; answered on the screening path.
    * **unfilled** — a plain input we can't fill (no profile match, or the
      profile's value is blank). These are surfaced for the user rather than
      guessed at: drafting prose for an input labelled "Last Name" or "Internal
      referral code" would be worse than leaving it blank and saying so.

    This three-way split is what lets the feature work on a portal nobody has
    seen before without inventing content for fields it doesn't understand.
    """
    fillable, questions, unfilled = [], [], []
    for field in fields or []:
        # Question-shaped controls always go down the screening path, even when
        # the profile knows the answer — that path checks the profile too, and it
        # stops a question from being keyword-matched to an unrelated field.
        if (field.get("kind") or "").lower() == "screening" or is_question(field):
            questions.append(field)
            continue
        if (field.get("type") or "").lower() == "file":
            continue                     # uploads are handled by the documents step
        key, phrase = match_profile_key(field)
        value = str(profile.get(key, "") or "").strip() if key else ""
        if not value:
            unfilled.append({
                "selector": field.get("selector", ""),
                "name": field.get("name", ""),
                "label": field.get("label", ""),
                "type": field.get("type", ""),
                "required": bool(field.get("required")),
                "profile_key": key,
                "reason": (f"apply_profile.{key} is empty" if key
                           else "no matching profile field"),
            })
            continue
        options = [str(o) for o in (field.get("options") or [])]
        value, snapped = _snap_to_option(value, options)
        fillable.append({
            "selector": field.get("selector", ""),
            "name": field.get("name", ""),
            "label": field.get("label", ""),
            "type": field.get("type", ""),
            "required": bool(field.get("required")),
            "profile_key": key,
            "matched_on": phrase,
            "value": value,
            "snapped_to_option": snapped,
            "source": "profile",
        })
    return fillable, questions, unfilled


def plan_screening_answers(questions: list[dict], target: TargetRole | None,
                           *, company: str = "", profile: dict | None = None,
                           model: str | None = None,
                           max_words: int | None = None) -> list[dict]:
    """Answer each screening question, in order of how much we trust the source:

    1. **the answers bank** — you've approved this answer before (``source: bank``)
    2. **the apply-profile** — a standing fact like work authorization or salary
       expectation (``source: profile``); no model call, nothing to verify
    3. **a fresh draft** — grounded in the profile + this job (``source: new``),
       marked ``verified: False`` so the confirmation summary can flag it

    Failures are captured per question so one bad item can't sink a whole form.
    """
    from ..generate import generate_answer

    profile = profile or {}
    out = []
    for field in questions or []:
        question = (field.get("label") or field.get("question")
                    or field.get("name") or "").strip()
        if not question:
            continue
        options = [str(o) for o in (field.get("options") or [])]
        entry = {
            "selector": field.get("selector", ""),
            "name": field.get("name", ""),
            "question": question,
            "type": field.get("type", ""),
            "required": bool(field.get("required")),
            "options": options,
            "answer": "",
            "source": "",
            "verified": False,
            "match_id": "",
            "match_score": 0.0,
            "snapped_to_option": False,
            "error": "",
        }

        # Protected characteristics, attestations and consents are the user's to
        # answer. Never drafted, never taken from the bank, never banked — and no
        # model call is spent on them, which over a batch is real time saved.
        if is_sensitive(question):
            entry.update({"source": "manual", "verified": False,
                          "sensitive": True,
                          "error": "left for you: sensitive or consent question"})
            out.append(entry)
            continue

        match, match_score = answers_bank.find_match(question)
        entry["match_score"] = match_score
        if match is not None:
            entry.update({
                "answer": match.get("answer", ""),
                "source": "bank",
                "verified": bool(match.get("verified")),
                "match_id": match.get("id", ""),
                "matched_question": match.get("question", ""),
            })
        else:
            # The nearest miss is remembered either way, so that an approved
            # answer is filed as an alternate phrasing of an existing record
            # rather than as a near-duplicate.
            near, near_score = answers_bank.find_match(
                question, threshold=answers_bank.MERGE_THRESHOLD
            )
            if near is not None:
                entry["merge_into"] = near.get("id", "")
                entry["merge_score"] = near_score
                entry["matched_question"] = near.get("question", "")

            # A standing fact from the apply-profile (work authorization, salary
            # expectation, notice period). No model call, nothing to verify.
            key, phrase = match_profile_key(field | {"label": question}, QUESTION_FIELDS)
            value = str(profile.get(key, "") or "").strip() if key else ""
            if value:
                entry.update({"answer": value, "source": "profile", "verified": True,
                              "profile_key": key, "matched_on": phrase})
            else:
                ask = question
                if options:
                    ask += ("\n\nChoose exactly one of these options and reply with it "
                            "verbatim: " + " | ".join(options))
                try:
                    entry["answer"] = generate_answer(
                        ask, target, model=model, max_words=max_words
                    )
                    entry["source"] = "new"
                    entry["verified"] = False
                except Exception as e:
                    entry["error"] = str(e)
                    entry["source"] = "failed"

        if entry["answer"] and options:
            entry["answer"], entry["snapped_to_option"] = _snap_to_option(
                entry["answer"], options
            )
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# The worklist — what's left to apply to
# --------------------------------------------------------------------------- #
# Indeed's own apply flow is off-limits (their terms); links that merely redirect
# through Indeed to a company's real ATS are fine, and are only distinguishable
# after following the redirect.
_BLOCKED_APPLY_HOSTS = ("smartapply.indeed.com", "linkedin.com/jobs/easy-apply")


def is_blocked_apply_url(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _BLOCKED_APPLY_HOSTS)


def candidates(*, limit: int = 50, since: str = "", company: str = "",
               source: str = "", include_attempted: bool = False) -> list[dict]:
    """Jobs ready to be applied to, in the order they should be worked through.

    A job qualifies when it has a generated application, an apply URL, and hasn't
    been applied to or dismissed. Jobs whose last attempt already reached a
    terminal state drop off automatically, so a batch that stops halfway can just
    re-fetch this list and carry on — no cursor to keep, nothing to reset.

    Ordered by priority pin, then repeat-company (portals you already have logins
    and saved details for), then newest.
    """
    attempted: set[str] = set()
    if not include_attempted:
        for s in apply_sessions.list_sessions(limit=1000):
            if s.get("status") in apply_sessions.TERMINAL and s.get("job_key"):
                attempted.add(s["job_key"])

    from ..intake.companies import is_repeat

    rank = {"high": 0, "medium": 1, "low": 2}
    out = []
    for job in store.list_queue():
        if job.applied or job.irrelevant or job.status in ("applied", "sent"):
            continue
        if not (job.apply_url or "").startswith("http"):
            continue
        if not (job.notes or "").strip():
            continue                     # nothing generated for it yet
        if job.key_id in attempted:
            continue
        if since and (job.found_at or "") < since:
            continue
        if company and company.lower() not in (job.company or "").lower():
            continue
        if source and (job.source or "") != source:
            continue
        out.append({
            "key_id": job.key_id,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "apply_url": job.apply_url,
            "run_id": (job.notes or "").strip(),
            "source": job.source,
            "found_at": job.found_at,
            "priority": job.priority_override or "",
            "repeat_company": is_repeat(job.company),
            "ats": detect_ats(job.apply_url),
            "likely_blocked": is_blocked_apply_url(job.apply_url),
        })

    # Two stable passes: newest first, then grouped by priority and repeat-company,
    # so within each group the freshest postings come first.
    out.sort(key=lambda j: j["found_at"] or "", reverse=True)
    out.sort(key=lambda j: (rank.get(j["priority"], 3),
                            0 if j["repeat_company"] else 1))
    return out[: max(1, int(limit))]


# --------------------------------------------------------------------------- #
# The three public steps
# --------------------------------------------------------------------------- #
def prepare(*, job_url: str, company: str = "", title: str = "",
            description: str = "", location: str = "", contact_email: str = "",
            fields: list[dict] | None = None, run_id: str = "",
            model: str | None = None, max_words: int | None = None,
            regenerate: bool = False, dest_dir: str | None = None) -> dict:
    """Do everything up to (but never including) submitting the form."""
    if not (job_url or "").strip():
        raise ValueError("A job URL is required.")

    job = resolve_job(job_url=job_url, company=company, title=title,
                      description=description, location=location,
                      contact_email=contact_email)
    target = job.to_target_role()

    warnings: list[str] = []
    if not (target.description or "").strip():
        warnings.append(
            "No job description was captured, so the résumé, cover letter and any "
            "drafted answers are tailored to the job title alone."
        )

    # Find the application already generated for this job before generating a new
    # one. A queued job records its run id in `notes`, so a job generated earlier
    # (in the Library, in Bulk, from the queue) is reused instead of spending
    # minutes re-running the local model for the same posting.
    bundle, gen_error, reused_run = None, "", False
    if not regenerate:
        candidate = run_id or (job.notes or "").strip()
        if candidate:
            bundle = runs_store.get_run(candidate)
            if bundle is not None:
                reused_run = True
            elif run_id:
                gen_error = f"Run {run_id!r} not found; generated a fresh application instead."
    if bundle is None:
        try:
            from ..pipeline import run as run_pipeline

            bundle = run_pipeline(target, model=model)
        except Exception as e:
            gen_error = str(e)
    if gen_error:
        warnings.append(f"Generation problem: {gen_error}")

    run_id = (bundle or {}).get("run_id", "")
    if reused_run:
        warnings.append(
            f"Reused the application already generated for this job "
            f"({run_id}, {bundle.get('created_at', 'unknown date')}). "
            f"Ask to regenerate if the posting or your profile has changed since."
        )
    documents: dict = {}
    if run_id:
        store.update_status(job.key_id, "generated", notes=run_id)
        try:
            documents = materialize_documents(run_id, dest_dir)
        except Exception as e:
            warnings.append(f"Could not render documents for upload: {e}")
    for kind, doc in documents.items():
        if doc.get("error"):
            warnings.append(f"{kind.replace('_', ' ')} PDF failed to render: {doc['error']}")

    # Fill plan: standard fields from the apply-profile, the rest as screening.
    from ..intake.companies import load_apply_profile

    profile = load_apply_profile()
    if not profile:
        warnings.append(
            "data/apply_profile.json is empty or missing — no standard fields could "
            "be filled. Copy data/apply_profile.sample.json and fill it in."
        )
    planned, question_fields, unfilled = plan_standard_fields(fields or [], profile)
    screening = plan_screening_answers(question_fields, target, company=job.company,
                                       profile=profile, model=model,
                                       max_words=max_words)

    required_unfilled = [
        f.get("label") or f.get("name") or "(unlabelled field)"
        for f in unfilled if f.get("required")
    ]
    if required_unfilled:
        warnings.append(
            "REQUIRED fields left blank, fill these in yourself before submitting: "
            + ", ".join(required_unfilled)
        )
    for s in screening:
        if s.get("options") and not s.get("snapped_to_option") and s["answer"] not in s["options"]:
            warnings.append(
                f"'{s['question'][:60]}' expects one of its listed options but the "
                f"answer doesn't match one — check it before submitting."
            )

    # Remember the portal for this company, so the next posting from them starts
    # with its apply URL and ATS already known (the repeat-company path).
    ats = detect_ats(job_url)
    if job.company:
        try:
            from ..intake.companies import save_company

            save_company(job.company, {"last_apply_url": job_url, "ats": ats})
        except Exception:
            pass                          # company memory is a convenience, not a gate

    # Remember the form itself. Reading a career page is the most expensive part
    # of applying, and employers reuse one form across every posting — so the next
    # application to this site can skip the read and fill from here instead.
    template = None
    if fields:
        try:
            from ..intake import form_templates

            template = form_templates.remember(job_url, fields, ats=ats,
                                               company=job.company)
        except Exception:
            pass                          # the cache is an optimisation, never a gate

    session = apply_sessions.new_session(
        job_url=job_url, company=job.company, title=job.title,
        job_key=job.key_id, run_id=run_id, ats=ats, reused_run=reused_run,
        form_template_id=(template or {}).get("id", ""),
        form_seen_before=bool(template and (template.get("times_used") or 0) > 1),
        documents=documents,
        standard_fields=planned,
        screening_answers=screening,
        unfilled_fields=unfilled,
        warnings=warnings,
        extracted_field_count=len(fields or []),
    )
    session["review"] = review_flags(session)
    session["summary"] = build_summary(session)
    return session


def build_summary(session: dict) -> dict:
    """The confirmation payload: what will be submitted, and what to look at twice."""
    screening = session.get("screening_answers") or []
    reused = [s for s in screening if s.get("source") == "bank"]
    from_profile = [s for s in screening if s.get("source") == "profile"]
    manual = [s for s in screening if s.get("source") == "manual"]
    drafted = [s for s in screening if s.get("source") == "new"]
    failed = [s for s in screening if s.get("source") == "failed"]
    docs = session.get("documents") or {}
    return {
        "job": {
            "company": session.get("company", ""),
            "title": session.get("title", ""),
            "url": session.get("job_url", ""),
        },
        "documents": {
            k: {"rel_path": v.get("rel_path", ""), "path": v.get("path", ""),
                "url": v.get("url", ""), "error": v.get("error", "")}
            for k, v in docs.items()
        },
        "standard_fields": [
            {"label": f.get("label") or f.get("name"), "value": f.get("value"),
             "from": f"apply_profile.{f.get('profile_key')}"}
            for f in (session.get("standard_fields") or [])
        ],
        "answers_reused": [
            {"question": s["question"], "answer": s["answer"],
             "previously_answered": s.get("matched_question", ""),
             "confidence": s.get("match_score", 0.0)}
            for s in reused
        ],
        "answers_from_profile": [
            {"question": s["question"], "answer": s["answer"],
             "from": f"apply_profile.{s.get('profile_key', '')}"}
            for s in from_profile
        ],
        "answers_new": [
            {"question": s["question"], "answer": s["answer"],
             "unverified": True}
            for s in drafted
        ],
        "answers_for_you": [
            {"question": s["question"],
             "why": "protected characteristic or consent — yours to answer"}
            for s in manual
        ],
        "answers_failed": [
            {"question": s["question"], "error": s.get("error", "")} for s in failed
        ],
        "left_blank": [
            {"label": f.get("label") or f.get("name"), "required": f.get("required"),
             "reason": f.get("reason", "")}
            for f in (session.get("unfilled_fields") or [])
        ],
        "counts": {
            "standard_fields": len(session.get("standard_fields") or []),
            "reused": len(reused),
            "from_profile": len(from_profile),
            "newly_drafted": len(drafted),
            "failed": len(failed),
            "left_blank": len(session.get("unfilled_fields") or []),
        },
        "warnings": session.get("warnings") or [],
        "review": session.get("review") or review_flags(session),
        "requires_confirmation": True,
        "note": (
            f"{len(drafted)} answer(s) were drafted fresh and are NOT verified against "
            "your profile history — read those closely."
            if drafted else
            "Every answer came from your profile or the answers bank."
        ),
    }


def review_flags(session: dict) -> dict:
    """What on this prepared application actually needs the user's eyes.

    The user always clicks submit themselves, so this is not a permission gate —
    it is a triage signal for reviewing at speed. A `clean` application is one
    where every value came from something they already vetted (the bank, or their
    own profile), nothing was drafted fresh, no required field is blank, and every
    dropdown answer is a real option: glance and submit.

    Anything listed in `needs_review` is a thing to read before clicking. In a
    batch this is the difference between skimming and re-reading every field.
    """
    reasons: list[str] = []
    screening = session.get("screening_answers") or []

    drafted = [s for s in screening if s.get("source") == "new"]
    if drafted:
        reasons.append(
            f"{len(drafted)} answer(s) drafted fresh and never reviewed: "
            + "; ".join(s["question"][:60] for s in drafted[:3])
        )
    failed = [s for s in screening if s.get("source") == "failed"]
    if failed:
        reasons.append(f"{len(failed)} question(s) could not be answered")
    manual = [s for s in screening if s.get("source") == "manual"]
    if manual:
        reasons.append(
            f"{len(manual)} sensitive/consent question(s) for you to answer: "
            + "; ".join(s["question"][:60] for s in manual[:3])
        )
    empty = [s for s in screening
             if s.get("source") != "manual" and not (s.get("answer") or "").strip()]
    if empty:
        reasons.append(f"{len(empty)} question(s) left with no answer")

    required_blank = [f for f in (session.get("unfilled_fields") or []) if f.get("required")]
    if required_blank:
        reasons.append(
            "required field(s) left blank: "
            + ", ".join((f.get("label") or f.get("name") or "?")[:40] for f in required_blank[:3])
        )

    # Option-based controls whose answer isn't actually one of the options would
    # either fail validation or submit something unintended.
    off_option = [s for s in screening
                  if s.get("source") != "manual"
                  and s.get("options") and s["answer"] not in s["options"]]
    if off_option:
        reasons.append(f"{len(off_option)} dropdown/radio answer(s) don't match the options")

    docs = session.get("documents") or {}
    if not (docs.get("resume") or {}).get("path") and not (docs.get("resume") or {}).get("url"):
        reasons.append("no résumé was rendered for upload")
    if any(d.get("error") for d in docs.values()):
        reasons.append("a document failed to render")

    if not session.get("run_id"):
        reasons.append("no generated application is attached to this job")

    warnings = [w for w in (session.get("warnings") or [])
                if not w.startswith("Reused the application")]
    if warnings:
        reasons.append(f"{len(warnings)} warning(s) on this application")

    return {
        "clean": not reasons,
        "needs_review": reasons,
        "counts": {
            "reused": sum(1 for s in screening if s.get("source") == "bank"),
            "from_profile": sum(1 for s in screening if s.get("source") == "profile"),
            "newly_drafted": len(drafted),
            "for_you": len(manual),
            "required_blank": len(required_blank),
        },
    }


def confirm(session_id: str, *, approved: bool, edits: dict | None = None,
            note: str = "", submit_by: str = "agent") -> dict:
    """Record the user's decision. Submission may proceed only if this says so.

    On approval, edited values replace the drafted ones and every newly drafted
    answer enters the bank (verified — the user signed off on it). On rejection
    nothing is banked, and the attempt is still logged.

    ``submit_by`` decides who clicks the button. ``"agent"`` returns
    ``may_submit: True``. ``"me"`` means the user will click it themselves — on a
    portal behind a login, a CAPTCHA, or a multi-step Workday flow — so
    ``may_submit`` stays **False** and the caller hands the browser over. The
    application is still fully prepared and the answers are still banked; the
    attempt is logged when the user confirms they submitted it.
    """
    session = apply_sessions.get_session(session_id)
    if session is None:
        raise ValueError(f"No apply session {session_id!r}.")
    if session.get("status") == apply_sessions.APPROVED:
        # Safe retry/polling behavior for ChatGPT/Codex and the web approval
        # center. Never bank answers twice when a client reconnects after the
        # user already made the decision.
        by = session.get("submit_by") or "agent"
        return {
            "session_id": session_id,
            "approved": True,
            "already_decided": True,
            "may_submit": by == "agent",
            "submit_by": by,
            "awaiting_user_submit": by == "me",
            "banked": session.get("banked_answers") or [],
            "note": "This exact application was already approved; no answers were banked again.",
        }
    if session.get("status") in apply_sessions.TERMINAL:
        raise ValueError(
            f"Session {session_id} is already {session['status']} and cannot be re-confirmed."
        )

    edits = edits or {}
    if edits:
        for entry in session.get("screening_answers") or []:
            for key in (entry.get("selector"), entry.get("name"), entry.get("question")):
                if key and key in edits:
                    entry["answer"] = str(edits[key])
                    entry["edited"] = True
                    break
        for field in session.get("standard_fields") or []:
            for key in (field.get("selector"), field.get("name"), field.get("label")):
                if key and key in edits:
                    field["value"] = str(edits[key])
                    field["edited"] = True
                    break

    if not approved:
        apply_sessions.set_status(session_id, apply_sessions.REJECTED,
                                  note=note or "rejected by user",
                                  screening_answers=session.get("screening_answers"),
                                  standard_fields=session.get("standard_fields"))
        log_outcome(session_id, status="rejected", note=note)
        return {"session_id": session_id, "approved": False, "may_submit": False,
                "banked": [], "note": "Nothing was submitted and nothing was banked."}

    banked = []
    for entry in session.get("screening_answers") or []:
        if entry.get("source") == "bank" and entry.get("match_id") and not entry.get("edited"):
            answers_bank.record_use(entry["match_id"])
            continue
        # Standing profile facts (work authorization, notice period, salary,
        # etc.) remain sourced from apply_profile.json.  They are not newly
        # drafted answers and duplicating them in the fuzzy bank would create a
        # second source of truth.  A user edit is the exception: the approved
        # edited value is an intentional answer worth remembering.
        if entry.get("source") == "profile" and not entry.get("edited"):
            continue
        # Protected characteristics and consents never enter the bank, even when
        # the user typed one in themselves on this form. Banking a demographic
        # answer would silently reuse it on every future application; disclosure
        # is a per-application choice, so it stays a per-application choice.
        if entry.get("source") == "manual" or entry.get("sensitive"):
            continue
        if not entry.get("answer"):
            continue
        # Newly drafted (or user-edited) answers are banked as verified: the user
        # has just read and approved them in the confirmation summary.
        try:
            rec = answers_bank.save_answer(
                entry["question"], entry["answer"],
                source_company=session.get("company", ""),
                verified=True,
                merge_into=entry.get("merge_into", "") or (
                    entry.get("match_id", "") if entry.get("edited") else ""
                ),
            )
            answers_bank.record_use(rec["id"])
            banked.append({"id": rec["id"], "question": entry["question"],
                           "merged": bool(entry.get("merge_into"))})
        except ValueError:
            continue

    by = "me" if (submit_by or "").strip().lower() in ("me", "user", "human") else "agent"
    apply_sessions.set_status(
        session_id, apply_sessions.APPROVED, note=note or "approved by user",
        approved_at=datetime.now().isoformat(timespec="seconds"),
        screening_answers=session.get("screening_answers"),
        standard_fields=session.get("standard_fields"),
        banked_answers=banked,
        submit_by=by,
    )
    banked_note = f"{len(banked)} answer(s) added to or refreshed in the bank."
    return {
        "session_id": session_id,
        "approved": True,
        # Only the agent clicking counts as permission for the agent to click.
        "may_submit": by == "agent",
        "submit_by": by,
        "awaiting_user_submit": by == "me",
        "banked": banked,
        "note": (
            banked_note if by == "agent" else
            f"{banked_note} The form is filled and ready. Submit it yourself, then "
            f"log the outcome so the job is marked applied."
        ),
    }


def log_outcome(session_id: str, *, status: str, note: str = "",
                verified_success: bool | None = None,
                submitted_by: str = "") -> dict:
    """Record a terminal outcome against the existing queue job and the session.

    `status` is one of submitted | rejected | failed. This is called for **every**
    attempt regardless of how it ended — that is the hard rule the tracker relies
    on to never lose an application.

    `submitted_by` is "agent" or "me": the job is marked applied either way, so an
    application the user finished by hand still lands in the tracker. Defaults to
    whoever the confirmation step said would submit.
    """
    session = apply_sessions.get_session(session_id)
    if session is None:
        raise ValueError(f"No apply session {session_id!r}.")

    status = (status or "").strip().lower()
    if status not in {"submitted", "rejected", "failed"}:
        raise ValueError("status must be one of: submitted, rejected, failed")

    by = (submitted_by or session.get("submit_by") or "agent").strip().lower()
    by = "me" if by in ("me", "user", "human") else "agent"

    # An agent that clicked submit can — and must — confirm the site's success
    # state before claiming the application went through; a silently failed
    # validation is not a submission. When the USER clicked it they are the one
    # who saw the result, so their word is the evidence. Demanding proof the agent
    # cannot have would only force the attempt to go unlogged, which is worse.
    if status == "submitted" and by == "agent" and verified_success is not True:
        raise ValueError(
            "submitted requires verified_success=true after observing the site's "
            "success state. If the user submitted it themselves, pass "
            "submitted_by='me'."
        )

    now = datetime.now().isoformat(timespec="seconds")
    job_key = session.get("job_key", "")
    banked = session.get("banked_answers") or []

    entry = {
        "at": now,
        "kind": "apply",
        "status": status,
        "session_id": session_id,
        "url": session.get("job_url", ""),
        "run_id": session.get("run_id", ""),
        "ats": session.get("ats", ""),
        "submitted_by": by if status == "submitted" else "",
        "note": note,
        "verified_success": verified_success,
        "answers_reused": sum(1 for s in (session.get("screening_answers") or [])
                              if s.get("source") == "bank"),
        "answers_added": len(banked),
    }

    if job_key:
        # Submitted marks the job applied; a decline or failure leaves it in the
        # queue (still generated) so it can be retried — but is logged either way.
        store.record_apply_outcome(
            job_key, entry,
            status="applied" if status == "submitted" else "",
            applied=True if status == "submitted" else None,
        )

    if status != "rejected":       # rejection already stamped by confirm()
        apply_sessions.set_status(session_id, status, note=note,
                                  outcome_logged_at=now,
                                  submitted_by=entry["submitted_by"],
                                  verified_success=verified_success)

    return {"session_id": session_id, "status": status, "job_key": job_key,
            "submitted_by": entry["submitted_by"],
            "applied": status == "submitted",
            "logged": entry, "answers_added": len(banked)}
