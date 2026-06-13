"""Safe, semi-auto application assistant.

Opens a company career portal in a REAL (headed) browser, fills the repeated
fields from your apply-profile, uploads your resume/cover letter, answers common
screening questions, then STOPS at the review page. You review and click Submit.

It never clicks the final Submit, never solves CAPTCHAs, never creates accounts.
Per-ATS templates (Workday / Greenhouse / Lever / generic) handle field differences.

Run on your HOST (not the headless API container):

    pip install playwright && playwright install chromium
    python -m resume_gen.automation.playwright_apply --url "<apply url>" \
        --resume output/<folder>/<Company>_<Title>_KK_Resume.pdf \
        --cover output/<folder>/<Company>_<Title>_KK_Cover.pdf

    # or pull a queued job by key (reads apply_url and generated documents):
    python -m resume_gen.automation.playwright_apply --job <key_id>

A persistent browser profile is used (./.pw-profile) so your saved logins stick.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import ROOT
from ..config import settings


def _load_apply_profile() -> dict:
    from ..intake.companies import load_apply_profile

    return load_apply_profile()


def _job_from_queue(key_id: str) -> dict | None:
    """Look up a queued job's apply_url/company by key via the running API."""
    import httpx

    try:
        jobs = httpx.get("http://localhost:8088/jobs", timeout=15).json()["jobs"]
    except Exception:
        return None
    return next((j for j in jobs if j.get("key_id") == key_id), None)


def _artifact(folder: Path, generic: str, pattern: str) -> str:
    old = folder / generic
    if old.exists():
        return str(old)
    matches = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(matches[0]) if matches else ""


def _generated_docs(job: dict) -> tuple[str, str]:
    notes = job.get("notes") or ""
    if not notes:
        return "", ""
    folder = (settings.output_dir / Path(notes).name).resolve()
    if not folder.is_dir():
        return "", ""
    return (
        _artifact(folder, "resume.pdf", "*_Resume.pdf"),
        _artifact(folder, "cover_letter.pdf", "*_Cover.pdf"),
    )


def detect_ats(url: str) -> str:
    u = (url or "").lower()
    if "myworkdayjobs.com" in u or "/wday/" in u:
        return "workday"
    if "greenhouse.io" in u or "boards.greenhouse" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    return "generic"


# --------------------------------------------------------------------------- #
# Field filling (Playwright page passed in)
# --------------------------------------------------------------------------- #
def _fill(page, selectors: list[str], value: str) -> bool:
    if not value:
        return False
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                el.fill(value)
                return True
        except Exception:
            continue
    return False


def _upload(page, selectors: list[str], path: str) -> bool:
    if not path or not Path(path).exists():
        return False
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count():
                el.set_input_files(str(path))
                return True
        except Exception:
            continue
    return False


def fill_common(page, p: dict, resume: str, cover: str) -> list[str]:
    """Fill the fields every portal shares. Returns a log of what was filled."""
    log = []
    pairs = [
        ("first name", ["input[name*='first' i]", "input[id*='first' i]", "input[autocomplete='given-name']"], p.get("firstName")),
        ("last name", ["input[name*='last' i]", "input[id*='last' i]", "input[autocomplete='family-name']"], p.get("lastName") or p.get("fullName")),
        ("email", ["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"], p.get("email")),
        ("phone", ["input[type='tel']", "input[name*='phone' i]", "input[id*='phone' i]", "input[name*='mobile' i]"], p.get("phone")),
        ("city", ["input[name*='city' i]", "input[id*='city' i]", "input[autocomplete='address-level2']"], p.get("city")),
        ("province", ["input[name*='province' i]", "input[name*='state' i]", "input[autocomplete='address-level1']"], p.get("province")),
        ("country", ["input[name*='country' i]", "input[autocomplete='country-name']"], p.get("country")),
        ("linkedin", ["input[name*='linkedin' i]", "input[placeholder*='linkedin' i]"], p.get("linkedin")),
        ("portfolio/website", ["input[name*='website' i]", "input[name*='portfolio' i]"], p.get("portfolio")),
    ]
    for label, sels, val in pairs:
        if _fill(page, sels, val):
            log.append(f"filled {label}")

    if _upload(page, ["input[type='file'][name*='resume' i]", "input[type='file'][id*='resume' i]",
                      "input[type='file']"], resume):
        log.append("uploaded resume")
    if cover and _upload(page, ["input[type='file'][name*='cover' i]", "input[type='file'][id*='cover' i]"], cover):
        log.append("uploaded cover letter")
    return log


def answer_screening(page, p: dict) -> list[str]:
    """Best-effort answers to common Yes/No screening questions by matching label text."""
    log = []
    answers = p.get("commonAnswers", {})
    for question, answer in answers.items():
        key = question.split("?")[0][:25].lower()
        try:
            # radios/labels containing the answer text near the question
            label = page.locator(f"text=/{key}/i").first
            if label.count():
                opt = page.locator(f"label:has-text('{answer}')").first
                if opt.count() and opt.is_visible():
                    opt.click()
                    log.append(f"answered '{key}…' -> {answer}")
        except Exception:
            continue
    return log


def run_template(page, ats: str, p: dict, job: dict, resume: str, cover: str) -> list[str]:
    """Per-ATS entry point. They mostly share the common filler; hooks left for
    portal-specific quirks (Workday multi-step, Greenhouse/Lever single page)."""
    log = [f"ATS: {ats}"]
    if ats == "greenhouse":
        log += fill_common(page, p, resume, cover)
        log += answer_screening(page, p)
    elif ats == "lever":
        log += fill_common(page, p, resume, cover)
        log += answer_screening(page, p)
    elif ats == "workday":
        # Workday is multi-step; fill what's on the current step. Re-run after
        # you click "Next" if needed. (Login/account is left to you.)
        log += fill_common(page, p, resume, cover)
    else:
        log += fill_common(page, p, resume, cover)
        log += answer_screening(page, p)
    return log


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Semi-auto application autofill (stops before submit).")
    ap.add_argument("--url", help="application URL")
    ap.add_argument("--job", help="queued job key_id (reads apply_url from the queue)")
    ap.add_argument("--resume", help="path to resume PDF")
    ap.add_argument("--cover", help="path to cover letter PDF")
    args = ap.parse_args(argv)

    p = _load_apply_profile()
    job = {}
    url = args.url
    if args.job:
        job = _job_from_queue(args.job) or {}
        url = url or job.get("apply_url")
    if not url:
        print("No URL. Pass --url or --job <key_id>.", file=sys.stderr)
        return 2

    generated_resume, generated_cover = _generated_docs(job) if job else ("", "")
    resume = args.resume or generated_resume or p.get("resumePath", "")
    cover = args.cover or generated_cover or p.get("coverLetterPath", "")
    ats = detect_ats(url)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 3

    profile_dir = str(ROOT / ".pw-profile")   # persistent profile = saved logins
    shots = ROOT / "data" / "job-applications" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"Opening ({ats}): {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        log = run_template(page, ats, p, job, resume, cover)
        print("\n".join("  - " + x for x in log))

        # Save company details for reuse on the next posting from this company.
        company = job.get("company") or ""
        if company:
            from ..intake.companies import save_company
            save_company(company, {"last_apply_url": url, "ats": ats})

        shot = shots / f"{(company or 'apply').lower().replace(' ', '_')}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            print(f"Screenshot: {shot}")
        except Exception:
            pass

        print("\nSTOPPED before submit. Review the form, then click Submit yourself.")
        print("Press Enter here to close the browser…")
        try:
            input()
        except EOFError:
            page.wait_for_timeout(60000)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
