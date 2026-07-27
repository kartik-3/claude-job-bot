"""Jobvite hosted job-board scraper.

Jobvite hosts public boards at jobs.jobvite.com/{company}/jobs — plain
server-rendered HTML, all jobs on one page, no auth. There is no public
JSON API without an API key, so this parses the list markup:

    <td class="jv-job-list-name"><a href="/{company}/job/{id}">Title</a></td>
    <td class="jv-job-list-location">Location</td>

Posted dates are not exposed on the board, so posted_at is always None.

Slug format in sources.yaml: the board name.
    e.g.  nutanix   →  https://jobs.jobvite.com/nutanix/jobs
"""
import html
import logging
import re
import time

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_BASE = "https://jobs.jobvite.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}

def _clean(text: str) -> str:
    """Strip tags, unescape entities, and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


_ROW_RE = re.compile(
    r'<td class="jv-job-list-name">\s*'
    r'<a href="(?P<path>/[^"]+/job/[^"]+)">(?P<title>.*?)</a>\s*</td>\s*'
    r'<td class="jv-job-list-location">\s*(?P<location>.*?)\s*</td>',
    re.S,
)


class JobviteScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip().strip("/")
        if not slug or "/" in slug:
            raise ValueError(
                f"Jobvite slug must be the bare board name "
                f"(e.g. 'nutanix' for jobs.jobvite.com/nutanix/jobs), got: {slug!r}"
            )
        url = f"{_BASE}/{slug}/jobs"

        for attempt in range(2):
            resp = requests.get(url, headers=_HEADERS, timeout=30)
            if resp.status_code < 500:
                break
            if attempt == 0:
                logger.warning("jobvite/%s: HTTP %d — retrying in 10s", slug, resp.status_code)
                time.sleep(10)
        resp.raise_for_status()

        jobs: list[Job] = []
        seen: set[str] = set()
        for m in _ROW_RE.finditer(resp.text):
            path = m.group("path")
            if path in seen:
                continue
            seen.add(path)
            title = _clean(m.group("title"))
            location = _clean(m.group("location")) or None
            job_url = f"{_BASE}{path}"
            jobs.append(
                Job(
                    id=make_job_id(company.name, title, job_url),
                    company=company.name,
                    title=title,
                    url=job_url,
                    apply_url=job_url,
                    ats="jobvite",
                    description=None,
                    location=location,
                    remote="remote" in location.lower() if location else None,
                    posted_at=None,  # not exposed on Jobvite boards
                )
            )
        return jobs
