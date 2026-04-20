import logging

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        url = _API.format(slug=company.slug)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        jobs: list[Job] = []
        for item in data.get("jobs", []):
            job_url: str = item.get("absolute_url", "")
            location: str = (item.get("location") or {}).get("name", "") or ""
            jobs.append(
                Job(
                    id=make_job_id(company.name, item["title"], job_url),
                    company=company.name,
                    title=item["title"],
                    url=job_url,
                    apply_url=job_url,
                    ats="greenhouse",
                    description=item.get("content"),
                    location=location or None,
                    remote="remote" in location.lower() if location else None,
                    posted_at=item.get("updated_at"),
                )
            )
        logger.debug("greenhouse/%s: fetched %d jobs", company.slug, len(jobs))
        return jobs
