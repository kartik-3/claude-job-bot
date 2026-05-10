"""Workable job board scraper (browser-based).

Workable's career site (apply.workable.com/{shortcode}/) is a React SPA
protected by Cloudflare JS challenge — direct HTTP requests are blocked.
Strategy:
  1. Load the careers page in Chromium to pass the Cloudflare JS challenge.
  2. POST to the v3 jobs API from inside the browser context (using the
     session cookie established by step 1) to fetch all job listings.
  3. Paginate using the cursor token returned in "nextPage" response field.

The v3 API uses cursor-based pagination:
    POST https://apply.workable.com/api/v3/accounts/{shortcode}/jobs
    Body (page 1): {"query":"","department":[],"location":[],"workplace":[],"worktype":[]}
    Body (page N): {same as page 1, plus "token": "<nextPage value from prev response>"}
    Response: {"total": N, "results": [...], "nextPage": "<cursor>" | null}

Slug format in sources.yaml:
    {shortcode}

Examples:
    huggingface
    innovaccer-analytics
    covergo

How to find the shortcode for any company:
    Visit apply.workable.com/{shortcode}/ — the shortcode is the path segment.
"""
import logging

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)


def _parse_workable_date(date_str: str | None) -> str | None:
    """Return ISO-8601 date (YYYY-MM-DD) from Workable's ISO timestamp, or None."""
    if not date_str:
        return None
    try:
        from datetime import datetime
        return (
            datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            .date()
            .isoformat()
        )
    except (ValueError, AttributeError):
        return None


def _extract_location(item: dict) -> str | None:
    """Return a human-readable location string from a Workable v3 job item."""
    loc = item.get("location")
    if isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        joined = ", ".join(p for p in parts if p)
        if joined:
            return joined
    locs = item.get("locations")
    if isinstance(locs, list) and locs:
        first = locs[0]
        if isinstance(first, dict):
            parts = [first.get("city"), first.get("region"), first.get("country")]
            joined = ", ".join(p for p in parts if p)
            if joined:
                return joined
        if isinstance(first, str):
            return first
    return None


class WorkableScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        from playwright.sync_api import sync_playwright

        shortcode = (company.slug or "").strip()
        if not shortcode:
            raise ValueError(f"Workable shortcode required, got: {shortcode!r}")

        careers_url = f"https://apply.workable.com/{shortcode}/"
        api_url = f"https://apply.workable.com/api/v3/accounts/{shortcode}/jobs"

        # POST inside browser context to inherit the Cloudflare session cookie.
        fetch_js = """
        async ([url, body]) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', url, true);
                xhr.setRequestHeader('Accept', 'application/json');
                xhr.setRequestHeader('Content-Type', 'application/json');
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
                xhr.send(JSON.stringify(body));
            });
        }
        """

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

            logger.debug("workable/%s: loading %s", shortcode, careers_url)
            # "load" not "networkidle" — Cloudflare keeps polling so networkidle
            # never fires; extra wait gives the JS challenge time to resolve.
            page.goto(careers_url, wait_until="load", timeout=60_000)
            page.wait_for_timeout(4_000)

            base_body: dict = {
                "query": "",
                "department": [],
                "location": [],
                "workplace": [],
                "worktype": [],
            }
            body = base_body.copy()
            page_num = 0

            while True:
                result = page.evaluate(fetch_js, [api_url, body])

                if isinstance(result, dict) and "error" in result:
                    logger.error(
                        "workable/%s: fetch error %s on page %d",
                        shortcode, result["error"], page_num,
                    )
                    break

                if page_num == 0:
                    total = result.get("total", 0)
                    logger.debug("workable/%s: total jobs = %d", shortcode, total)

                results = result.get("results", [])
                if not results:
                    break

                for item in results:
                    title = item.get("title", "")
                    job_code = item.get("shortcode", "")
                    apply_url = f"https://apply.workable.com/{shortcode}/j/{job_code}/"
                    location = _extract_location(item)
                    remote = item.get("remote")
                    posted_at = _parse_workable_date(item.get("published"))

                    jobs.append(
                        Job(
                            id=make_job_id(company.name, title, apply_url),
                            company=company.name,
                            title=title,
                            url=apply_url,
                            apply_url=apply_url,
                            ats="workable",
                            description=None,
                            location=location,
                            remote=bool(remote) if remote is not None else None,
                            posted_at=posted_at,
                        )
                    )

                next_token = result.get("nextPage")
                if not next_token:
                    break

                body = {**base_body, "token": next_token}
                page_num += 1

            browser.close()

        logger.debug("workable/%s: fetched %d jobs", shortcode, len(jobs))
        return jobs
