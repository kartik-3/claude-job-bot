"""SAP SuccessFactors (SF) career site scraper (browser-based).

SuccessFactors external career sites are server-rendered Java apps with no
public REST API — job data is loaded client-side after a JSESSIONID handshake.
Strategy:
  1. Navigate to the SF career site in Chromium to establish a session.
  2. Intercept the internal job-search API response the page fires on load.
  3. Re-use the session cookies to paginate via page.evaluate().

Slug format in sources.yaml:
    {datacenter}/{companyId}

Examples:
    career44/SAP_SE
    career1/SUNPHARMA

How to find the slug for any company:
    Visit the company's SF career site. The URL is typically:
        https://{datacenter}.sapsf.com/careers?company={companyId}&lang=en_US
    From that URL: datacenter = subdomain, companyId = company= query param.
"""
import logging
import re

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


def _parse_sf_date(date_str: str | None) -> str | None:
    """Return ISO-8601 date from a SuccessFactors date string, or None."""
    if not date_str:
        return None
    try:
        from datetime import datetime
        # SF returns dates like "May 5, 2026" or ISO strings
        for fmt in ("%b %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return None


class SuccessFactorsScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        from playwright.sync_api import sync_playwright

        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"SuccessFactors slug must be 'career{{N}}/{{companyId}}' "
                f"(e.g. 'career44/SAP_SE'), got: {slug!r}"
            )

        datacenter, company_id = slug.split("/", 1)
        base_host = f"https://{datacenter}.sapsf.com"
        careers_url = f"{base_host}/careers?company={company_id}&lang=en_US"

        captured: dict = {"api_base": None, "first_data": None}
        # Patterns the SF SPA uses for job search API calls
        _API_PATTERNS = [
            r"/api/reqs/",
            r"/careersection/",
            r"/jobboard/",
            r"/postings/",
        ]

        jobs: list[Job] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def on_response(response):
                if captured["first_data"] is not None:
                    return
                url = response.url
                if not any(re.search(p, url) for p in _API_PATTERNS):
                    return
                try:
                    data = response.json()
                except Exception:
                    return
                # Detect a job-listing response by presence of typical SF keys
                if any(k in data for k in ("jobReqList", "jobs", "requisitions", "results")):
                    captured["api_base"] = url
                    captured["first_data"] = data
                    logger.debug(
                        "successfactors/%s: captured API at %s", slug, url
                    )

            page.on("response", on_response)

            logger.debug("successfactors/%s: loading %s", slug, careers_url)
            page.goto(careers_url, wait_until="networkidle", timeout=60_000)

            if not captured["first_data"]:
                logger.warning(
                    "successfactors/%s: no job-listing API response captured — "
                    "the career site may require authentication or have moved. "
                    "Check %s manually.",
                    slug, careers_url,
                )
                browser.close()
                return []

            def _extract_jobs(data: dict) -> list[dict]:
                for key in ("jobReqList", "jobs", "requisitions", "results"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return []

            def _parse_job(item: dict) -> Job | None:
                # SF uses varying field names — try common variants
                title = (
                    item.get("jobTitle")
                    or item.get("title")
                    or item.get("externalTitle")
                    or ""
                )
                if not title:
                    return None

                job_id = (
                    item.get("jobReqId")
                    or item.get("id")
                    or item.get("requisitionId")
                    or ""
                )
                location = (
                    item.get("primaryLocation")
                    or item.get("location")
                    or item.get("city")
                    or ""
                )
                date_str = (
                    item.get("postingDate")
                    or item.get("postedDate")
                    or item.get("startDate")
                    or None
                )
                posted_at = _parse_sf_date(str(date_str) if date_str else None)

                job_url = (
                    item.get("applyUrl")
                    or item.get("jobUrl")
                    or f"{base_host}/careers?company={company_id}&jobId={job_id}&lang=en_US"
                )

                return Job(
                    id=make_job_id(company.name, title, job_url),
                    company=company.name,
                    title=title,
                    url=job_url,
                    apply_url=job_url,
                    ats="successfactors",
                    description=None,
                    location=str(location) if location else None,
                    remote=None,
                    posted_at=posted_at,
                )

            # Process first captured page
            first_items = _extract_jobs(captured["first_data"])
            for item in first_items:
                job = _parse_job(item)
                if job:
                    jobs.append(job)

            # Attempt pagination if the API base URL is known and has offset/page params
            api_url = captured["api_base"]
            if api_url and first_items:
                fetch_js = """
                async ([url]) => {
                    return new Promise((resolve) => {
                        const xhr = new XMLHttpRequest();
                        xhr.open('GET', url, true);
                        xhr.setRequestHeader('Accept', 'application/json');
                        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                        xhr.withCredentials = true;
                        xhr.onload = function() {
                            if (xhr.status >= 200 && xhr.status < 300) {
                                try { resolve(JSON.parse(xhr.responseText)); }
                                catch (e) { resolve({ error: 'parse_error' }); }
                            } else {
                                resolve({ error: xhr.status });
                            }
                        };
                        xhr.onerror = function() { resolve({ error: 'network_error' }); };
                        xhr.send();
                    });
                }
                """

                # Build paginated URLs by incrementing offset/page params
                offset = len(first_items)
                while offset < _PAGE_SIZE * 20:  # safety cap: 2000 jobs
                    paginated_url = re.sub(
                        r"(offset|start|from)=\d+",
                        lambda m: f"{m.group(1)}={offset}",
                        api_url,
                    )
                    if paginated_url == api_url:
                        # URL has no offset param — can't paginate
                        break

                    result = page.evaluate(fetch_js, [paginated_url])
                    if isinstance(result, dict) and "error" in result:
                        logger.error(
                            "successfactors/%s: fetch error %s at offset %d",
                            slug, result["error"], offset,
                        )
                        break

                    items = _extract_jobs(result)
                    if not items:
                        break

                    for item in items:
                        job = _parse_job(item)
                        if job:
                            jobs.append(job)
                    offset += len(items)

            browser.close()

        logger.debug("successfactors/%s: fetched %d jobs", slug, len(jobs))
        return jobs
