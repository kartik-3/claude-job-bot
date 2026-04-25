"""Oracle HCM Cloud Candidate Experience scraper.

Uses the public recruitingCEJobRequisitions REST API — no auth required for
discovery. Applications require an Oracle account login, so all discovered
jobs land in the manual queue automatically.

Slug format in sources.yaml:
    {tenant}/{siteNumber}

Examples:
    jpmc/CX_1001

How to find the slug for any company:
    1. Visit the company's careers page.
    2. Find the link that redirects to a URL like:
           https://{tenant}.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{siteNumber}
    3. From that URL: tenant = subdomain before .fa.oraclecloud.com,
                      siteNumber = last path segment (e.g. CX_1001).
"""
import logging

import requests

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 25
_FACETS = "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
_EXPAND = "requisitionList.workLocation,requisitionList.secondaryLocations,requisitionList.requisitionFlexFields"


def _is_remote(workplace_type: str | None, location: str | None) -> bool | None:
    for text in (workplace_type or "", location or ""):
        if "remote" in text.lower():
            return True
    return None


class OracleScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"Oracle slug must be 'tenant/siteNumber' "
                f"(e.g. 'jpmc/CX_1001'), got: {slug!r}. "
                f"See scrapers/oracle.py for instructions."
            )

        tenant, site = slug.split("/", 1)
        host = f"{tenant}.fa.oraclecloud.com"
        api_url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}",
        }

        jobs: list[Job] = []
        offset = 0

        while True:
            finder = (
                f"findReqs;siteNumber={site},"
                f"facetsList={_FACETS},"
                f"limit={_PAGE_SIZE},"
                f"offset={offset}"
            )
            resp = requests.get(
                api_url,
                params={"onlyData": "true", "expand": _EXPAND, "finder": finder},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            wrapper = (data.get("items") or [{}])[0]
            total: int = wrapper.get("TotalJobsCount", 0)
            postings: list[dict] = wrapper.get("requisitionList") or []

            if not postings:
                break

            for item in postings:
                title: str = item.get("Title", "")
                job_id: str = str(item.get("Id", ""))
                job_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}"
                location: str | None = item.get("PrimaryLocation") or None

                jobs.append(
                    Job(
                        id=make_job_id(company.name, title, job_url),
                        company=company.name,
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        ats="oracle",
                        description=item.get("ShortDescriptionStr") or None,
                        location=location,
                        remote=_is_remote(item.get("WorkplaceType"), location),
                        posted_at=item.get("PostedDate"),
                    )
                )

            offset += len(postings)
            if offset >= total:
                break

        logger.debug("oracle/%s: fetched %d jobs", slug, len(jobs))
        return jobs
