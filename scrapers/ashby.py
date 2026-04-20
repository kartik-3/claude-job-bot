import logging

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        url = _API.format(slug=company.slug)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        jobs: list[Job] = []
        for item in data.get("jobPostings", []):
            job_url: str = item.get("jobUrl", "")
            location: str = item.get("locationName", "") or ""
            is_remote: bool | None = item.get("isRemote")
            if is_remote is None and location:
                is_remote = "remote" in location.lower()
            jobs.append(
                Job(
                    id=make_job_id(company.name, item["title"], job_url),
                    company=company.name,
                    title=item["title"],
                    url=job_url,
                    apply_url=job_url,
                    ats="ashby",
                    description=item.get("descriptionHtml"),
                    location=location or None,
                    remote=is_remote,
                    posted_at=item.get("publishedDate"),
                )
            )
        logger.debug("ashby/%s: fetched %d jobs", company.slug, len(jobs))
        return jobs
