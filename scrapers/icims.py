"""iCIMS (Jibe Marketing Cloud) job board scraper.

Used by companies whose careers site is powered by the Jibe/iCIMS platform.
The underlying JSON API is public — no authentication required.

Slug format in sources.yaml: {careers_host}/{path_prefix}
  e.g.  jobs.booking.com/booking
        www.github.careers/careers-home

API:  https://{careers_host}/api/jobs?limit={PAGE_SIZE}&offset={n}
Job URL: https://{careers_host}/{path_prefix}/jobs/{req_id}?lang=en-us
"""
import logging
from datetime import datetime, timezone

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


def _parse_icims_date(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("+0000", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


class IcimsScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"iCIMS slug must be 'careers_host/path_prefix', got: {slug!r}"
            )

        careers_host, path_prefix = slug.split("/", 1)
        api_base = f"https://{careers_host}/api/jobs"
        job_url_base = f"https://{careers_host}/{path_prefix}/jobs"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        jobs: list[Job] = []
        offset = 0

        while True:
            params = {"limit": _PAGE_SIZE, "offset": offset, "lang": "en-us"}
            resp = requests.get(api_base, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            total: int = data.get("totalCount", data.get("count", 0))
            items: list[dict] = data.get("jobs", [])
            if not items:
                break

            for item in items:
                j = item.get("data", item)
                req_id: str = str(j.get("req_id") or j.get("slug") or "")
                title: str = j.get("title", "")
                if not req_id or not title:
                    continue

                job_url = f"{job_url_base}/{req_id}?lang=en-us"

                # Build location string from available fields
                full_loc: str = j.get("full_location") or ""
                if not full_loc:
                    parts = [j.get("city"), j.get("state"), j.get("country")]
                    full_loc = ", ".join(p for p in parts if p) or ""

                is_remote: bool | None = None
                if full_loc:
                    is_remote = "remote" in full_loc.lower()

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        ats="icims",
                        description=j.get("description"),
                        location=full_loc or None,
                        remote=is_remote,
                        posted_at=_parse_icims_date(j.get("posted_date")),
                    )
                )

            offset += len(items)
            if offset >= total:
                break

        logger.debug("icims/%s: fetched %d jobs", slug, len(jobs))
        return jobs
