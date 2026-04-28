"""Eightfold.ai job board scraper.

Used by companies whose careers page is hosted at {tenant}.eightfold.ai/careers.
The underlying JSON API is public — no authentication required.

Slug format in sources.yaml: the tenant subdomain only.
  e.g.  astrazeneca  →  https://astrazeneca.eightfold.ai/careers

The domain parameter sent to the API is derived as {tenant}.com, which works
for all known Eightfold tenants. If a company ever needs a different domain,
extend the slug to  tenant/domain.com  and split on '/'.
"""
import logging
from datetime import datetime

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 10  # Eightfold API hard-caps results at 10 per page


def _parse_eightfold_date(ts: int | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


class EightfoldScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        tenant = (company.slug or "").strip()
        if not tenant:
            raise ValueError(
                f"Eightfold slug must be the tenant subdomain "
                f"(e.g. 'astrazeneca' for astrazeneca.eightfold.ai), got: {tenant!r}"
            )

        api_url = f"https://{tenant}.eightfold.ai/api/apply/v2/jobs"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"https://{tenant}.eightfold.ai/careers",
        }

        jobs: list[Job] = []
        start = 0

        while True:
            params = {
                "domain": f"{tenant}.com",
                "num_jobs": _PAGE_SIZE,
                "query": "",
                "location": "",
                "pid": "",
                "start": start,
                "triggerGoButton": "false",
            }
            resp = requests.get(api_url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            total: int = data.get("count", 0)
            positions: list[dict] = data.get("positions", [])
            if not positions:
                break

            for item in positions:
                title: str = item.get("name", "")
                job_url: str = (
                    item.get("canonicalPositionUrl")
                    or f"https://{tenant}.eightfold.ai/careers"
                )
                location: str = item.get("location") or ""
                work_option: str = item.get("work_location_option", "")
                is_remote: bool | None = (
                    True if work_option == "remote"
                    else ("remote" in location.lower() if location else None)
                )
                posted_at = _parse_eightfold_date(item.get("t_create"))

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        ats="eightfold",
                        description=None,
                        location=location or None,
                        remote=is_remote,
                        posted_at=posted_at,
                    )
                )

            start += len(positions)
            if start >= total:
                break

        logger.debug("eightfold/%s: fetched %d jobs", tenant, len(jobs))
        return jobs
