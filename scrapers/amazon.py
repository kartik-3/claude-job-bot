"""Amazon Jobs scraper.

Uses the public search JSON API — no authentication required for discovery.
Applications redirect to account.amazon.com, so discovered jobs go to the
manual queue automatically.

Slug format in sources.yaml:
    Comma-separated ISO-3166-alpha-3 country codes.

Examples:
    USA
    IND
    USA,IND

How to find valid country codes:
    Visit https://www.amazon.jobs and observe normalized_country_code values
    in the facets response (e.g. USA, IND, GBR, DEU, CAN, AUS).
"""
import logging
from datetime import datetime

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.amazon.jobs/en/search.json"
_PAGE_SIZE = 100
_JOB_BASE = "https://www.amazon.jobs"


def _parse_date(raw: str | None) -> str | None:
    """Convert 'April 25, 2026' → '2026-04-25'; return None on failure."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return raw


def _is_remote(location: str | None) -> bool | None:
    if not location:
        return None
    return "remote" in location.lower()


class AmazonScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "IND").strip()
        country_codes = [c.strip() for c in slug.split(",") if c.strip()]
        if not country_codes:
            raise ValueError(
                f"Amazon slug must be comma-separated country codes "
                f"(e.g. 'USA' or 'USA,IND'), got: {slug!r}. "
                f"See scrapers/amazon.py for details."
            )

        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        jobs: list[Job] = []
        offset = 0

        while True:
            params: list[tuple[str, str]] = [
                ("result_limit", str(_PAGE_SIZE)),
                ("offset", str(offset)),
            ]
            for code in country_codes:
                params.append(("normalized_country_code[]", code))

            resp = requests.get(_BASE_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            total: int = data.get("hits", 0)
            postings: list[dict] = data.get("jobs", [])
            if not postings:
                break

            for item in postings:
                title: str = item.get("title", "")
                job_path: str = item.get("job_path", "")
                job_url = f"{_JOB_BASE}{job_path}" if job_path else _JOB_BASE
                apply_url: str | None = item.get("url_next_step") or job_url
                location: str | None = item.get("location") or None

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=apply_url,
                        ats="amazon",
                        description=item.get("description") or None,
                        location=location,
                        remote=_is_remote(location),
                        posted_at=_parse_date(item.get("posted_date")),
                    )
                )

            offset += len(postings)
            if offset >= total:
                break

        logger.debug("amazon/%s: fetched %d jobs", slug, len(jobs))
        return jobs
