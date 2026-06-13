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


def _clean_na(value) -> str:
    """The local collector writes the literal 'N/A' for empty fields; treat it
    (and None) as an empty string."""
    s = str(value or "").strip()
    return "" if s.upper() == "N/A" else s


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


# --------------------------------------------------------------------------- #
# Local collector: the Resume_Scraper app (Tampermonkey userscript -> CSV store)
# exposes GET /api/jobs. We pull the jobs you saved in the browser straight into
# the queue. Base URL defaults to the Docker host gateway since the resume-api
# runs in a container and the collector publishes :8765 on the host.
# --------------------------------------------------------------------------- #
def fetch_collector(src: dict) -> list[JobPosting]:
    base = (
        src.get("base")
        or os.getenv("COLLECTOR_BASE")
        or "http://host.docker.internal:8765"
    ).rstrip("/")
    statuses = {str(s).lower() for s in (src.get("statuses") or ["saved"])}
    exclude_flagged = bool(src.get("exclude_flagged", True))
    exclude_applied = bool(src.get("exclude_applied", True))

    r = httpx.get(f"{base}/api/jobs", headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()

    out: list[JobPosting] = []
    for j in r.json().get("jobs", []):
        if statuses and str(j.get("status", "saved")).lower() not in statuses:
            continue
        if exclude_flagged and str(j.get("flagged", "")).lower() == "yes":
            continue
        if exclude_applied and str(j.get("applied", "")).lower() == "yes":
            continue

        emails = j.get("contact_emails", "")
        if isinstance(emails, list):
            emails = ", ".join(str(e) for e in emails if e)
        emails = _clean_na(emails)
        first_email = emails.split(",")[0].strip() if emails else ""
        desc = _clean_na(j.get("description_summary"))

        out.append(JobPosting(
            source="collector",
            source_company=j.get("source_site") or "collector",
            job_id=str(j.get("job_key") or j.get("source_url") or ""),
            company=_clean_na(j.get("company")),
            title=_clean_na(j.get("job_title")),
            location=_clean_na(j.get("location")),
            description=desc,
            apply_url=j.get("apply_url") or j.get("source_url") or "",
            contact_email=first_email or _find_email(desc),
            posted=_clean_na(j.get("posted_date")),
        ))
    return out


# --------------------------------------------------------------------------- #
# RSS / Atom feeds (e.g. Job Bank job-search RSS). Parsed with stdlib XML so we
# add no dependency. Each item/entry -> one JobPosting.
# --------------------------------------------------------------------------- #
def _xml_text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _find(el, *names):
    """Find the first child whose tag (ignoring namespace) matches any name."""
    for child in el.iter():
        tag = child.tag.split("}")[-1].lower()
        if tag in names:
            return child
    return None


def fetch_rss(src: dict) -> list[JobPosting]:
    import xml.etree.ElementTree as ET

    url = src["url"]
    r = httpx.get(url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    # RSS <item> or Atom <entry>
    items = [e for e in root.iter() if e.tag.split("}")[-1].lower() in ("item", "entry")]
    domain = urlparse(url).netloc
    out: list[JobPosting] = []
    for it in items:
        title = _xml_text(_find(it, "title"))
        # link: RSS uses <link>text</link>; Atom uses <link href="..."/>
        link_el = _find(it, "link")
        link = _xml_text(link_el) or (link_el.get("href") if link_el is not None else "")
        desc_el = _find(it, "description", "summary", "content")
        desc = _html_to_text(_xml_text(desc_el))
        posted = _xml_text(_find(it, "pubdate", "published", "updated"))

        # company: explicit, else parsed from "Title - Company" / "Title at Company"
        company = src.get("company", "")
        if not company:
            m = re.search(r"\s[-–]\s(.+)$", title) or re.search(r"\sat\s(.+)$", title, re.I)
            company = (m.group(1).strip() if m else "") or domain

        out.append(JobPosting(
            source="rss", source_company=src.get("company") or domain,
            job_id=link or title,
            company=company,
            title=re.sub(r"\s[-–]\s.+$", "", title).strip() or title,
            description=desc,
            apply_url=link,
            contact_email=_find_email(desc),
            posted=posted,
        ))
    return out


# --------------------------------------------------------------------------- #
# Job Bank (Canada) — its RSS is dead, so scrape the search results page and pull
# each posting's description + contact email from the posting's JSON-LD.
# --------------------------------------------------------------------------- #
_BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_JOBBANK = "https://www.jobbank.gc.ca"


def _txt(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_jobbank_detail(html: str) -> tuple[str, str]:
    """(description, contact_email) from a Job Bank posting page. The real content
    is in [property='description'] (+ a .job-posting-brief with location/salary)."""
    soup = BeautifulSoup(html, "html.parser")
    brief = soup.select_one(".job-posting-brief")
    desc = soup.select_one("[property='description']")
    parts = [_txt(brief) if brief else "", desc.get_text("\n", strip=True) if desc else ""]
    text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(p for p in parts if p)).strip()
    if not text:
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return text[:8000], _find_email(html)


def fetch_jobbank(src: dict) -> list[JobPosting]:
    search = src.get("search") or src.get("searchstring") or src.get("keyword") or ""
    location = src.get("location") or src.get("locationstring") or ""
    limit = int(src.get("limit", 25))
    want_detail = src.get("detail", True)
    params = {"searchstring": search, "locationstring": location, "sort": src.get("sort", "M")}

    out: list[JobPosting] = []
    with httpx.Client(headers=_BROWSER_UA, timeout=_TIMEOUT, follow_redirects=True) as c:
        r = c.get(f"{_JOBBANK}/jobsearch/jobsearch", params=params)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.resultJobItem")[:limit]:
            href = a.get("href", "")
            m = re.search(r"/jobposting/(\d+)", href)
            jid = m.group(1) if m else ""
            apply_url = f"{_JOBBANK}/jobsearch/jobposting/{jid}" if jid else _JOBBANK + href.split(";")[0]
            title = _txt(a.select_one(".noctitle"))
            company = _txt(a.select_one(".business"))
            location_t = _txt(a.select_one(".location")).replace("Location", "").strip()
            posted = _txt(a.select_one(".date"))
            desc, email = "", ""
            if want_detail and jid:
                try:
                    d = c.get(apply_url)
                    desc, email = _parse_jobbank_detail(d.text)
                except httpx.HTTPError:
                    pass
            out.append(JobPosting(
                source="jobbank", source_company="jobbank",
                job_id=jid or apply_url, company=company, title=title,
                location=location_t, description=desc, apply_url=apply_url,
                contact_email=email, posted=posted,
            ))
    return out


def fetch_source(src: dict) -> list[JobPosting]:
    """Dispatch one source-config entry to the right fetcher."""
    t = (src.get("type") or "").lower()
    if t == "jobbank":
        return fetch_jobbank(src)
    if t in ("rss", "atom"):
        return fetch_rss(src)
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
    if t in ("collector", "scraper"):
        return fetch_collector(src)
    raise ValueError(f"Unknown source type: {t!r}")
