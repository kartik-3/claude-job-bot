"""SmartRecruiters job board scraper.

SmartRecruiters exposes a fully public REST API — no authentication needed.

Slug format in sources.yaml:
    {CompanyIdentifier}

Examples:
    AristaNetworks
    Okta

How to find the slug for any company:
    Visit the company's SmartRecruiters job board at:
        https://jobs.smartrecruiters.com/{CompanyIdentifier}
    The identifier is the path segment after the domain.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class SmartRecruitersScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip()
        if not slug:
            raise ValueError(f"SmartRecruiters slug required, got: {slug!r}")

        base_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        jobs: list[Job] = []
        offset = 0

        while True:
            for attempt in range(2):
                resp = requests.get(
                    base_url,
                    params={"limit": _PAGE_SIZE, "offset": offset},
                    timeout=30,
                )
                if resp.status_code < 500:
                    break
                if attempt == 0:
                    logger.warning(
                        "smartrecruiters/%s: HTTP %d — retrying in 10s",
                        slug, resp.status_code,
                    )
                    time.sleep(10)
            resp.raise_for_status()

            data = resp.json()
            postings = data.get("content", [])
            if not postings:
                break

            for item in postings:
                title = item.get("name", "")
                posting_id = item.get("id", "")
                loc = item.get("location", {})
                location = loc.get("fullLocation") or loc.get("city") or ""
                remote = loc.get("remote")

                released = item.get("releasedDate", "")
                try:
                    posted_at = (
                        datetime.fromisoformat(released.replace("Z", "+00:00"))
                        .date()
                        .isoformat()
                        if released
                        else None
                    )
                except (ValueError, AttributeError):
                    posted_at = None

                apply_url = f"https://jobs.smartrecruiters.com/{slug}/{posting_id}"

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, apply_url),
                        company=company.name,
                        title=title,
                        url=apply_url,
                        apply_url=apply_url,
                        ats="smartrecruiters",
                        description=None,
                        location=location or None,
                        remote=bool(remote) if remote is not None else None,
                        posted_at=posted_at,
                    )
                )

            offset += len(postings)
            if offset >= data.get("totalFound", 0):
                break

        logger.debug("smartrecruiters/%s: fetched %d jobs", slug, len(jobs))
        return jobs
