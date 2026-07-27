"""Microsoft careers scraper.

Microsoft careers (jobs.careers.microsoft.com) is backed by a public
Eightfold-style "pcsx" search API on apply.careers.microsoft.com — no
authentication needed for discovery. Applications require a Microsoft
account login, so discovered jobs land in the manual queue automatically.

    GET https://apply.careers.microsoft.com/api/pcsx/search
        ?domain=microsoft.com&query=&location={slug}&start={offset}

The API hard-caps results at 10 per page; paginate with `start` until
`count` is reached. Job descriptions are not included in the list
response and are left empty (the evaluator falls back to title-only).

Slug format in sources.yaml: a location search string, geo-matched by the API.
    e.g.  India   or  Hyderabad, TS, India
Empty slug is rejected — the unfiltered board is ~1500 jobs.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_API_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
_JOB_URL_PREFIX = "https://apply.careers.microsoft.com"
_PAGE_SIZE = 10  # API hard-caps at 10 per page
_MAX_PAGES = 100
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _parse_posted_ts(ts: int | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


def _is_remote(position: dict) -> bool | None:
    work_option = (position.get("workLocationOption") or "").lower()
    if work_option == "remote":
        return True
    loc_text = " ".join(position.get("locations") or []).lower()
    if "remote" in loc_text:
        return True
    if work_option in ("onsite", "hybrid"):
        return False
    return None


class MicrosoftScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        location = (company.slug or "").strip()
        if not location:
            raise ValueError(
                "Microsoft slug must be a location search string "
                f"(e.g. 'India'), got: {location!r}"
            )

        jobs: list[Job] = []
        start = 0
        for _ in range(_MAX_PAGES):
            params = {
                "domain": "microsoft.com",
                "query": "",
                "location": location,
                "start": start,
            }
            for attempt in range(2):
                resp = requests.get(_API_URL, params=params, headers=_HEADERS, timeout=30)
                if resp.status_code < 500:
                    break
                if attempt == 0:
                    logger.warning(
                        "microsoft/%s: HTTP %d — retrying in 10s", location, resp.status_code
                    )
                    time.sleep(10)
            resp.raise_for_status()

            data = resp.json().get("data") or {}
            positions = data.get("positions") or []
            if not positions:
                break

            for pos in positions:
                title = pos.get("name") or ""
                position_path = pos.get("positionUrl") or f"/careers/job/{pos.get('id')}"
                url = f"{_JOB_URL_PREFIX}{position_path}"
                loc_str = "; ".join(pos.get("locations") or []) or None
                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, url),
                        company=company.name,
                        title=title,
                        url=url,
                        apply_url=url,
                        ats="microsoft",
                        description=None,
                        location=loc_str,
                        remote=_is_remote(pos),
                        posted_at=_parse_posted_ts(pos.get("postedTs")),
                    )
                )

            start += _PAGE_SIZE
            total = data.get("count") or 0
            if start >= total:
                break
            time.sleep(0.3)

        return jobs
