"""Workday job board discovery scraper.

Workday exposes a public POST-based search API per tenant — no authentication
needed for discovery. Applications still require a Workday account login, so
discovered jobs land in the manual queue automatically.

Slug format in sources.yaml:
    {tenant}.wd{n}/{site}

Examples:
    microsoft.wd1/MSFTExternal
    nvidia.wd5/NVIDIAExternalCareerSite
    jpmc.wd5/technology

How to find the slug for any company:
    1. Visit the company's careers page.
    2. Find the link that redirects to a URL like:
           https://{tenant}.wd{n}.myworkdayjobs.com/{site}/jobs
    3. From that URL: tenant = first part, wdN = the number, site = path segment.
"""
import logging
import re
from datetime import date, timedelta

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


_SKIP = "__skip__"  # sentinel: job is too old, discard it


def _parse_workday_date(posted_on: str | None) -> str | None:
    """Convert Workday's relative date string to ISO-8601 (YYYY-MM-DD).

    Returns _SKIP sentinel when the job is 30+ days old.
    Returns None for unrecognised formats — caller keeps the job with no date.
    """
    if not posted_on:
        return None
    text = posted_on.strip().lower()
    today = date.today()
    if text == "posted today":
        return today.isoformat()
    if text == "posted yesterday":
        return (today - timedelta(days=1)).isoformat()
    if "30+" in text:
        return _SKIP
    m = re.search(r"(\d+)\s+days?\s+ago", text)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    logger.warning("workday: unrecognised postedOn format %r — keeping job", posted_on)
    return None  # unknown format — keep with no posted_at


class WorkdayScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"Workday slug must be 'tenant.wdN/SiteName' "
                f"(e.g. 'microsoft.wd1/MSFTExternal'), got: {slug!r}. "
                f"See scrapers/workday.py for instructions on finding the slug."
            )

        host_part, site = slug.split("/", 1)
        # host_part is e.g. "microsoft.wd1"
        tenant = host_part.rsplit(".wd", 1)[0]
        host = f"{host_part}.myworkdayjobs.com"
        api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": f"https://{host}",
            "Referer": f"https://{host}/{site}/jobs",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        jobs: list[Job] = []
        offset = 0
        total = None  # latched from first page; Workday returns 0 on subsequent pages

        while True:
            resp = requests.post(
                api_url,
                json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            if not resp.content:
                logger.warning("workday/%s: empty response at offset=%d, stopping", slug, offset)
                break
            data = resp.json()

            postings = data.get("jobPostings", [])
            if not postings:
                break

            if total is None:
                total = data.get("total", 0)

            for item in postings:
                posted_at = _parse_workday_date(item.get("postedOn"))
                if posted_at is _SKIP:
                    continue  # 30+ days old — skip

                title = item.get("title", "")
                ext_path = item.get("externalPath", "")
                job_url = f"https://{host}/{site}{ext_path}" if ext_path else f"https://{host}/{site}/jobs"
                location = item.get("locationsText", "") or ""

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        ats="workday",
                        description=None,
                        location=location or None,
                        remote="remote" in location.lower() if location else None,
                        posted_at=posted_at,
                    )
                )

            offset += len(postings)
            if offset >= total:
                break

        logger.debug("workday/%s: fetched %d jobs", slug, len(jobs))
        return jobs
