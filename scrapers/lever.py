import logging
from datetime import datetime, timezone

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_API = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        url = _API.format(slug=company.slug)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        jobs: list[Job] = []
        for item in data:
            job_url: str = item.get("hostedUrl", "")
            location: str = (item.get("categories") or {}).get("location", "") or ""
            created_ms: int | None = item.get("createdAt")
            posted_at = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                if created_ms
                else None
            )
            jobs.append(
                Job(
                    id=make_job_id(company.name, item["text"], job_url),
                    company=company.name,
                    title=item["text"],
                    url=job_url,
                    apply_url=item.get("applyUrl"),
                    ats="lever",
                    description=item.get("description"),
                    location=location or None,
                    remote="remote" in location.lower() if location else None,
                    posted_at=posted_at,
                )
            )
        logger.debug("lever/%s: fetched %d jobs", company.slug, len(jobs))
        return jobs
