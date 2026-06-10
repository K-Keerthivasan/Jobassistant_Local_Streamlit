"""Per-platform fetchers. Each returns a list[JobPosting].

We target ATS JSON APIs (robust, no anti-bot) wherever possible:
  - Greenhouse: https://boards-api.greenhouse.io/v1/boards/<token>/jobs
  - Lever:      https://api.lever.co/v0/postings/<company>?mode=json
  - Workday:    POST https://<host>/wday/cxs/<tenant>/<site>/jobs  (+ detail GET)
The generic HTML fetcher is a best-effort fallback for arbitrary career pages.
"""

from __future__ import annotations

import html as _html
import os
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .models import JobPosting

_TIMEOUT = 25.0
_UA = {"User-Agent": "Mozilla/5.0 (compatible; resume-gen-intake/0.1)"}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def _html_to_text(s: str) -> str:
    if not s:
        return ""
    s = _html.unescape(s)
    text = BeautifulSoup(s, "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _find_email(text: str) -> str:
    """First HR-ish email in the text, else the first email, else ''. """
    if not text:
        return ""
    emails = _EMAIL_RE.findall(text)
    if not emails:
        return ""
    for e in emails:
        if re.search(r"hr|career|job|recruit|talent|hiring|apply|people", e, re.I):
            return e
    return emails[0]


# --------------------------------------------------------------------------- #
def fetch_greenhouse(token: str) -> list[JobPosting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = httpx.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out: list[JobPosting] = []
    for j in r.json().get("jobs", []):
        desc = _html_to_text(j.get("content", ""))
        out.append(JobPosting(
            source="greenhouse", source_company=token,
            job_id=str(j.get("id", "")),
            company=j.get("company_name") or token.replace("-", " ").title(),
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            description=desc,
            apply_url=j.get("absolute_url", ""),
            contact_email=_find_email(desc),
            posted=j.get("updated_at", ""),
        ))
    return out


def fetch_lever(company: str) -> list[JobPosting]:
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    r = httpx.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out: list[JobPosting] = []
    for j in r.json():
        cats = j.get("categories") or {}
        desc = j.get("descriptionPlain") or _html_to_text(j.get("description", ""))
        out.append(JobPosting(
            source="lever", source_company=company,
            job_id=str(j.get("id", "")),
            company=company.replace("-", " ").title(),
            title=j.get("text", ""),
            location=cats.get("location", ""),
            description=desc,
            apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
            contact_email=_find_email(desc),
            posted=str(j.get("createdAt", "")),
        ))
    return out


def _parse_workday(url: str) -> tuple[str, str, str]:
    """Derive (host, tenant, site) from a public Workday careers URL like
    https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers ."""
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.netloc
    tenant = host.split(".")[0]
    parts = [seg for seg in p.path.split("/") if seg and not _LOCALE_RE.match(seg)]
    site = parts[-1] if parts else tenant
    return host, tenant, site


def fetch_workday(url: str, limit: int = 20) -> list[JobPosting]:
    host, tenant, site = _parse_workday(url)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    r = httpx.post(
        f"{base}/jobs",
        headers={**_UA, "Content-Type": "application/json", "Accept": "application/json"},
        json={"limit": limit, "offset": 0, "searchText": "", "appliedFacets": {}},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    out: list[JobPosting] = []
    for jp in r.json().get("jobPostings", []):
        ext = jp.get("externalPath", "")
        apply_url = f"https://{host}{ext}"
        desc = ""
        try:
            d = httpx.get(f"{base}{ext}", headers=_UA, timeout=_TIMEOUT)
            info = d.json().get("jobPostingInfo", {})
            desc = _html_to_text(info.get("jobDescription", ""))
            apply_url = info.get("externalUrl") or info.get("jobPostingUrl") or apply_url
        except (httpx.HTTPError, ValueError):
            pass
        out.append(JobPosting(
            source="workday", source_company=tenant,
            job_id=ext or jp.get("bulletFields", [""])[0] or jp.get("title", ""),
            company=tenant.replace("-", " ").title(),
            title=jp.get("title", ""),
            location=jp.get("locationsText", ""),
            description=desc,
            apply_url=apply_url,
            contact_email=_find_email(desc),
            posted=jp.get("postedOn", ""),
        ))
    return out


def fetch_generic(url: str, company: str = "") -> list[JobPosting]:
    """Best-effort: pull one posting's worth of text from an arbitrary page."""
    r = httpx.get(url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.get_text().strip() if soup.title else url
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    domain = urlparse(url).netloc
    return [JobPosting(
        source="generic", source_company=company or domain,
        job_id=url,
        company=company or domain,
        title=title,
        description=text[:8000],
        apply_url=url,
        contact_email=_find_email(text),
    )]


# --------------------------------------------------------------------------- #
# Apify: run a job-scraping actor (Indeed, LinkedIn, etc.) and read its dataset.
# Every actor emits a different field shape, so map common job fields with
# fallbacks; a per-source `field_map` overrides any of them.
# --------------------------------------------------------------------------- #
_APIFY_BASE = "https://api.apify.com/v2"

_FIELD_DEFAULTS: dict[str, list[str]] = {
    "title": ["positionName", "title", "position", "jobTitle", "name"],
    "company": ["companyName", "company", "employer", "organization"],
    "location": ["location", "jobLocation", "formattedLocation", "city", "place"],
    "description": ["descriptionText", "description", "jobDescription", "fullDescription",
                    "snippet", "text"],
    "apply_url": ["externalApplyLink", "applyUrl", "url", "jobUrl", "link", "externalUrl"],
    "contact_email": ["contactEmail", "email", "hrEmail"],
    "job_id": ["id", "jobId", "jobkey", "key", "positionId"],
    "posted": ["postedAt", "postingDateParsed", "date", "publishedAt", "postedTime"],
}


def _pick(item: dict, keys: list[str]) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("displayName") or v.get("text") or ""
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v if x)
        if v not in (None, "", []):
            return str(v).strip()
    return ""


def fetch_apify(src: dict) -> list[JobPosting]:
    """Pull job items from Apify, either by running an actor synchronously
    (`actor` + `input`) or by reading an existing dataset (`dataset_id`).
    Token comes from the env var named in `token_env` (default APIFY_TOKEN)."""
    token = os.getenv(src.get("token_env", "APIFY_TOKEN"), "")
    if not token:
        raise ValueError(
            f"Apify token not set. Put it in .env as "
            f"{src.get('token_env', 'APIFY_TOKEN')}=apify_api_..."
        )

    overrides = src.get("field_map") or {}

    def keys_for(field: str) -> list[str]:
        ov = overrides.get(field)
        return ([ov] if ov else []) + _FIELD_DEFAULTS[field]

    if src.get("dataset_id"):
        label = src["dataset_id"]
        r = httpx.get(
            f"{_APIFY_BASE}/datasets/{src['dataset_id']}/items",
            params={"token": token, "clean": "true", "format": "json"},
            timeout=120.0,
        )
    else:
        actor = (src.get("actor") or "").replace("/", "~")
        if not actor:
            raise ValueError("Apify source needs 'actor' (e.g. 'misceres/indeed-scraper') or 'dataset_id'.")
        label = src.get("actor")
        # Actors can take minutes; run-sync waits and returns dataset items.
        r = httpx.post(
            f"{_APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
            params={"token": token},
            json=src.get("input") or {},
            timeout=float(src.get("timeout", 300)),
        )
    r.raise_for_status()
    items = r.json()

    out: list[JobPosting] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        desc = _pick(it, keys_for("description"))
        out.append(JobPosting(
            source="apify", source_company=str(label),
            job_id=_pick(it, keys_for("job_id")) or _pick(it, keys_for("apply_url")),
            company=_pick(it, keys_for("company")) or str(label),
            title=_pick(it, keys_for("title")),
            location=_pick(it, keys_for("location")),
            description=desc,
            apply_url=_pick(it, keys_for("apply_url")),
            contact_email=_pick(it, keys_for("contact_email")) or _find_email(desc),
            posted=_pick(it, keys_for("posted")),
        ))
    return out


def fetch_source(src: dict) -> list[JobPosting]:
    """Dispatch one source-config entry to the right fetcher."""
    t = (src.get("type") or "").lower()
    if t == "greenhouse":
        return fetch_greenhouse(src["company"])
    if t == "lever":
        return fetch_lever(src["company"])
    if t == "workday":
        return fetch_workday(src["url"], limit=int(src.get("limit", 20)))
    if t == "generic":
        return fetch_generic(src["url"], company=src.get("company", ""))
    if t == "apify":
        return fetch_apify(src)
    raise ValueError(f"Unknown source type: {t!r}")
