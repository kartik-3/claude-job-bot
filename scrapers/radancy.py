"""Radancy (TalentBrew) careers-site scraper.

Radancy hosts branded careers sites with a public AJAX search endpoint —
no authentication needed:

    GET https://{host}/search-jobs/results?CurrentPage={n}&RecordsPerPage=100&...
    Response: JSON {"results": "<html>", "hasJobs": true, ...}

The job list arrives as an HTML fragment; items look like:

    <a class="search-results-link" href="/job/{city}/{slug}/{siteId}/{jobId}"
       data-job-id="{jobId}">... <h2>Title</h2> ...
       <span class="job-location">Location</span> ...</a>

Total count comes from a data-total-results attribute in the fragment.
Posted dates are not exposed in the list, so posted_at is always None.

Slug format in sources.yaml: the careers host.
    e.g.  careers.astrazeneca.com
"""
import html
import logging
import re
import time

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 50
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

_ITEM_RE = re.compile(
    r'<a[^>]*class="search-results-link"[^>]*href="(?P<path>/job/[^"]+)"'
    r"(?P<body>.*?)</a>",
    re.S,
)
_TITLE_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_LOCATION_RE = re.compile(
    r'class="(?:job-location|search-result-location|job-info)[^"]*"[^>]*>(.*?)<', re.S
)
_TOTAL_RE = re.compile(r'data-total-results="(\d+)"')


def _clean(text: str) -> str:
    """Strip tags, unescape entities, and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


class RadancyScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        host = (company.slug or "").strip().rstrip("/")
        if not host or "/" in host:
            raise ValueError(
                f"Radancy slug must be a bare careers host "
                f"(e.g. 'careers.astrazeneca.com'), got: {host!r}"
            )
        api_url = f"https://{host}/search-jobs/results"

        jobs: list[Job] = []
        seen: set[str] = set()
        page = 1
        total: int | None = None
        for _ in range(_MAX_PAGES):
            params = {
                "ActiveFacetID": 0,
                "CurrentPage": page,
                "RecordsPerPage": _PAGE_SIZE,
                "SortCriteria": 0,
                "SortDirection": 1,
                "SearchResultsModuleName": "Search Results",
                "SearchFiltersModuleName": "Search Filters",
            }
            for attempt in range(2):
                resp = requests.get(api_url, params=params, headers=_HEADERS, timeout=30)
                if resp.status_code < 500:
                    break
                if attempt == 0:
                    logger.warning("radancy/%s: HTTP %d — retrying in 10s", host, resp.status_code)
                    time.sleep(10)
            resp.raise_for_status()

            fragment = resp.json().get("results") or ""
            if total is None:
                m = _TOTAL_RE.search(fragment)
                total = int(m.group(1)) if m else None

            page_jobs = 0
            for m in _ITEM_RE.finditer(fragment):
                path = m.group("path")
                if path in seen:
                    continue
                seen.add(path)
                page_jobs += 1
                body = m.group("body")
                title_m = _TITLE_RE.search(body)
                title = _clean(title_m.group(1)) if title_m else ""
                loc_m = _LOCATION_RE.search(body)
                location = _clean(loc_m.group(1)) if loc_m else None
                job_url = f"https://{host}{path}"
                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        ats="radancy",
                        description=None,
                        location=location,
                        remote="remote" in location.lower() if location else None,
                        posted_at=None,  # not exposed in the list fragment
                    )
                )

            if page_jobs == 0:
                break
            if total is not None and len(jobs) >= total:
                break
            page += 1
            time.sleep(0.3)

        return jobs
