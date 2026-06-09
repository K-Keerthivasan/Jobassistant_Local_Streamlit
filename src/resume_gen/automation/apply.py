"""Selenium-based auto-apply — Phase 3 scaffold.

The plan: small, per-site "adapter" classes (Indeed, LinkedIn Easy Apply,
Workday, Greenhouse, Lever, company forms) that know how to fill and submit one
site's application form with a generated resume/cover-letter. A custom scraper
feeds in job postings; n8n orchestrates the queue.

This file intentionally ships the interface + a no-op driver factory so the
structure is in place. Real adapters are added one site at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ApplyJob:
    apply_url: str
    resume_pdf: Path
    cover_letter_pdf: Path | None = None
    answers: dict[str, str] | None = None  # screening Q&A, name/email autofill, etc.


class SiteAdapter(Protocol):
    """One implementation per job site / ATS."""

    name: str

    def matches(self, url: str) -> bool: ...

    def apply(self, driver, job: ApplyJob) -> dict: ...


def make_driver(headless: bool = True):
    """Create a Selenium WebDriver. Imported lazily so the package works without
    a browser installed (e.g. for generation-only use)."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1696")
    return webdriver.Chrome(options=opts)


# Registry filled in as adapters are implemented.
ADAPTERS: list[SiteAdapter] = []


def apply_to(job: ApplyJob, *, headless: bool = True) -> dict:
    for adapter in ADAPTERS:
        if adapter.matches(job.apply_url):
            driver = make_driver(headless=headless)
            try:
                return adapter.apply(driver, job)
            finally:
                driver.quit()
    return {"status": "no_adapter", "url": job.apply_url,
            "note": "No site adapter implemented yet for this URL."}
