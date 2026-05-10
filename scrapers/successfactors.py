"""SAP SuccessFactors (SF) career site scraper (HTTP-based).

SuccessFactors external career sites render job listings as server-side HTML —
no JavaScript execution required.

URL pattern for job listings:
    https://{datacenter}.sapsf.com/career
        ?company={company_id}
        &career_ns=job_listing_summary
        &navBarLevel=JOB_SEARCH
        &lang=en_US
        &startrow={offset}   (increments of 25)

HTML structure:
    <tr class="data-row">
      <td class="colDate"><span class="jobDate">May 10, 2026</span></td>
      <td class="colTitle">
        <a class="jobTitle-link" href="/job/{slug}/{id}/">Title</a>
      </td>
      <td class="colFacility"><span class="jobFacility">Facility Name</span></td>
      <td class="colLocation"><span class="jobLocation">City, Country</span></td>
    </tr>

Slug format in sources.yaml:
    {datacenter}/{company_id}

The company_id is case-sensitive — use the exact casing that the SF career site
expects (typically lowercase). Test with:
    curl -s "https://{datacenter}.sapsf.com/career?company={company_id}&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH&lang=en_US" | grep "data-row"

Examples:
    career44/sunpharma

How to find the slug for any company:
    Visit the company's SF career site. The URL typically follows:
        https://{datacenter}.sapsf.com/careers?company={company_id}&lang=en_US
    OR navigate to their jobs listing page manually and look at the URL.
    Note: company_id is case-sensitive; try lowercase if uppercase returns an error.
"""
import logging
import re
import time
from datetime import datetime

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 25  # SF paginates in steps of 25
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_sf_date(date_str: str | None) -> str | None:
    """Return ISO-8601 date from a SuccessFactors date string, or None."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _fetch_page(session: requests.Session, base_url: str, startrow: int) -> str:
    """Fetch one page of job listings, retrying once on 5xx."""
    params = {
        "q": "",
        "sortColumn": "referencedate",
        "sortDirection": "desc",
    }
    if startrow > 0:
        params["startrow"] = startrow

    for attempt in range(2):
        resp = session.get(base_url, params=params, headers=_HEADERS, timeout=30)
        if resp.status_code < 500:
            break
        if attempt == 0:
            logger.warning(
                "successfactors: HTTP %d at startrow=%d — retrying in 10s",
                resp.status_code, startrow,
            )
            time.sleep(10)
    resp.raise_for_status()
    return resp.text


def _parse_jobs_from_html(html: str, base_host: str, company: Company) -> list[Job]:
    """Extract Job objects from one page of SF HTML."""
    jobs: list[Job] = []
    row_pattern = re.compile(
        r'<tr class="data-row">(.*?)</tr>',
        re.DOTALL,
    )
    for row_match in row_pattern.finditer(html):
        row = row_match.group(1)

        # Job title and relative URL
        link_m = re.search(
            r'class="jobTitle-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', row
        )
        if not link_m:
            continue
        href, title = link_m.group(1), link_m.group(2).strip()
        job_url = base_host + href if href.startswith("/") else href

        # Date
        date_m = re.search(r'class="jobDate"[^>]*>([^<]+)<', row)
        posted_at = _parse_sf_date(date_m.group(1) if date_m else None)

        # Location
        loc_m = re.search(r'class="jobLocation"[^>]*>\s*([^<]+?)\s*<', row)
        location = loc_m.group(1).strip() if loc_m else None

        jobs.append(
            Job(
                id=make_job_id(company.name, title, job_url),
                company=company.name,
                title=title,
                url=job_url,
                apply_url=job_url,
                ats="successfactors",
                description=None,
                location=location or None,
                remote=None,
                posted_at=posted_at,
            )
        )
    return jobs


def _parse_total(html: str) -> int | None:
    """Extract total job count from 'Results 1 – 25 of <b>355</b>'."""
    m = re.search(r'of\s+<b>(\d+)</b>', html)
    return int(m.group(1)) if m else None


class SuccessFactorsScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"SuccessFactors slug must be 'career{{N}}/{{company_id}}' "
                f"(e.g. 'career44/sunpharma'), got: {slug!r}"
            )

        datacenter, company_id = slug.split("/", 1)
        base_host = f"https://{datacenter}.sapsf.com"
        listing_url = (
            f"{base_host}/career"
            f"?company={company_id}"
            f"&career_ns=job_listing_summary"
            f"&navBarLevel=JOB_SEARCH"
            f"&lang=en_US"
        )

        session = requests.Session()
        jobs: list[Job] = []
        startrow = 0
        total: int | None = None

        while True:
            html = _fetch_page(session, listing_url, startrow)

            if total is None:
                total = _parse_total(html)
                if total is None:
                    # No results found (or wrong company ID)
                    logger.warning(
                        "successfactors/%s: could not parse total — "
                        "check that company_id is correct (case-sensitive). "
                        "Test URL: %s",
                        slug, listing_url,
                    )
                    break
                logger.debug("successfactors/%s: total jobs = %d", slug, total)

            page_jobs = _parse_jobs_from_html(html, base_host, company)
            if not page_jobs:
                break

            jobs.extend(page_jobs)
            startrow += _PAGE_SIZE

            if startrow >= total:
                break

        logger.debug("successfactors/%s: fetched %d jobs", slug, len(jobs))
        return jobs
