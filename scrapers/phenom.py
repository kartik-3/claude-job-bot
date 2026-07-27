"""Phenom People careers-site scraper.

Phenom hosts branded careers sites (careers.{company}.com) with a public
POST search API — no authentication needed:

    POST https://{host}/widgets
    Body: the standard "refineSearch" widget payload (see _payload below)
    Response: {"refineSearch": {"totalHits": N, "data": {"jobs": [...]}}}

Many Phenom sites merely front another ATS (check jobs[].applyUrl — if it
deep-links to Workday/Ashby/etc., prefer that scraper). Use this scraper
for companies natively on Phenom, where applyUrl stays on the same host.

Some Phenom hosts sit behind Cloudflare/Akamai and reject plain HTTP
(e.g. careers.swiggy.com, careers.nutanix.com) — those cannot use this
scraper; verify the /widgets endpoint responds before wiring a company.

Slug format in sources.yaml: the careers host.
    e.g.  careers.lilly.com
"""
import logging
import time
from datetime import datetime

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50
_MAX_PAGES = 100
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _payload(offset: int) -> dict:
    return {
        "lang": "en_us",
        "deviceType": "desktop",
        "country": "us",
        "pageName": "search-results",
        "ddoKey": "refineSearch",
        "sortBy": "",
        "subsearch": "",
        "from": offset,
        "jobs": True,
        "counts": True,
        "all_fields": ["category", "country", "state", "city", "type"],
        "size": _PAGE_SIZE,
        "clearAll": False,
        "jdsource": "facets",
        "isSliderEnable": False,
        "pageId": "page10",
        "siteType": "external",
        "keywords": "",
        "global": True,
        "selected_fields": {},
        "locationData": {},
    }


def _parse_posted_date(raw: str | None) -> str | None:
    """Phenom postedDate looks like '2026-07-10T00:00:00.000+0000'."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("+0000", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _extract_location(item: dict) -> str | None:
    multi = item.get("multi_location")
    if isinstance(multi, list) and multi:
        return "; ".join(multi)
    parts = [item.get("cityState"), item.get("country")]
    joined = ", ".join(p for p in parts if p)
    return joined or None


class PhenomScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        host = (company.slug or "").strip().rstrip("/")
        if not host or "/" in host:
            raise ValueError(
                f"Phenom slug must be a bare careers host "
                f"(e.g. 'careers.lilly.com'), got: {host!r}"
            )
        api_url = f"https://{host}/widgets"

        jobs: list[Job] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            for attempt in range(2):
                resp = requests.post(
                    api_url, json=_payload(offset), headers=_HEADERS, timeout=30
                )
                if resp.status_code < 500:
                    break
                if attempt == 0:
                    logger.warning(
                        "phenom/%s: HTTP %d — retrying in 10s", host, resp.status_code
                    )
                    time.sleep(10)
            resp.raise_for_status()

            refine = resp.json().get("refineSearch") or {}
            page_jobs = (refine.get("data") or {}).get("jobs") or []
            if not page_jobs:
                break

            for item in page_jobs:
                title = item.get("title") or ""
                job_id = item.get("jobId") or item.get("reqId") or ""
                apply_url = item.get("applyUrl") or ""
                url = apply_url or f"https://{host}/job/{job_id}"
                location = _extract_location(item)
                loc_lower = (location or "").lower()
                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, url),
                        company=company.name,
                        title=title,
                        url=url,
                        apply_url=apply_url or None,
                        ats="phenom",
                        description=item.get("descriptionTeaser"),
                        location=location,
                        remote="remote" in loc_lower if location else None,
                        posted_at=_parse_posted_date(item.get("postedDate")),
                    )
                )

            offset += _PAGE_SIZE
            total = refine.get("totalHits") or 0
            if offset >= total:
                break
            time.sleep(0.3)

        return jobs
