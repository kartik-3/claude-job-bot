"""Workday job board scraper using Playwright (browser-based).

Used for Workday tenants that block headless HTTP requests via Cloudflare.
Strategy:
  1. Load the careers page in a real Chromium browser — passes Cloudflare JS challenge.
  2. Intercept the CSRF token and cookies from the page's own first API request.
  3. Make paginated API calls using page.evaluate() (runs inside the browser,
     so Cloudflare treats it as a legitimate browser fetch).

Slug format: identical to workday — {tenant}.wd{n}/{site}
ATS type in sources.yaml: workday_browser
"""
import logging

from scrapers.base import BaseScraper, Company, Job, make_job_id
from scrapers.workday import _parse_workday_date

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


class WorkdayBrowserScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        from playwright.sync_api import sync_playwright

        slug = (company.slug or "").strip()
        if not slug or "/" not in slug:
            raise ValueError(
                f"workday_browser slug must be 'tenant.wdN/SiteName', got: {slug!r}"
            )

        host_part, site = slug.split("/", 1)
        tenant = host_part.rsplit(".wd", 1)[0]
        host = f"{host_part}.myworkdayjobs.com"
        careers_url = f"https://{host}/{site}/jobs"
        api_path = f"/wday/cxs/{tenant}/{site}/jobs"
        api_url = f"https://{host}{api_path}"

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
            # Save native fetch before any page scripts (e.g. AWS CloudWatch RUM cwr.js)
            # can override window.fetch — we'll call window.__nativeFetch in page.evaluate().
            context.add_init_script("window.__nativeFetch = window.fetch.bind(window);")

            page = context.new_page()

            # Intercept the page's own API request to capture the CSRF token
            captured: dict = {"csrf": "", "first_data": None}

            def on_response(response):
                if api_path in response.url and not captured["csrf"]:
                    tok = response.headers.get("x-calypso-csrf-token", "")
                    if tok:
                        captured["csrf"] = tok
                    try:
                        captured["first_data"] = response.json()
                    except Exception:
                        pass

            page.on("response", on_response)

            logger.debug("workday_browser/%s: loading %s", slug, careers_url)
            page.goto(careers_url, wait_until="networkidle", timeout=45_000)

            csrf_token = captured["csrf"]
            logger.debug(
                "workday_browser/%s: csrf=%s",
                slug,
                (csrf_token[:8] + "...") if csrf_token else "none",
            )

            # Build the JS fetch helper we'll call inside the browser context.
            # Running fetch() from the page bypasses Cloudflare's external-IP checks.
            # Use XMLHttpRequest instead of fetch — RUM scripts (cwr.js) don't override XHR.
            fetch_js = """
            async ([url, payload, csrf]) => {
                return new Promise((resolve) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', url, true);
                    xhr.setRequestHeader('Content-Type', 'application/json');
                    xhr.setRequestHeader('Accept', 'application/json');
                    if (csrf) xhr.setRequestHeader('X-Calypso-CSRF-Token', csrf);
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
                    xhr.send(JSON.stringify(payload));
                });
            }
            """

            def fetch_page(offset: int) -> dict | None:
                payload = {
                    "appliedFacets": {},
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                }
                # Use already-captured first page data to avoid a redundant request
                if offset == 0 and captured["first_data"]:
                    return captured["first_data"]
                result = page.evaluate(fetch_js, [api_url, payload, csrf_token])
                if isinstance(result, dict) and "error" in result:
                    logger.error(
                        "workday_browser/%s: fetch returned %s at offset %d",
                        slug, result["error"], offset,
                    )
                    return None
                return result

            offset = 0
            while True:
                data = fetch_page(offset)
                if not data:
                    break

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for item in postings:
                    posted_at = _parse_workday_date(item.get("postedOn"))
                    if posted_at is None:
                        continue

                    title = item.get("title", "")
                    ext_path = item.get("externalPath", "")
                    job_url = (
                        f"https://{host}/{site}{ext_path}"
                        if ext_path
                        else f"https://{host}/{site}/jobs"
                    )
                    location = item.get("locationsText", "") or ""

                    jobs.append(
                        Job(
                            id=make_job_id(company.name, title, job_url),
                            company=company.name,
                            title=title,
                            url=job_url,
                            apply_url=job_url,
                            ats="workday_browser",
                            description=None,
                            location=location or None,
                            remote="remote" in location.lower() if location else None,
                            posted_at=posted_at,
                        )
                    )

                offset += len(postings)
                if offset >= data.get("total", 0):
                    break

            browser.close()

        logger.debug("workday_browser/%s: fetched %d jobs", slug, len(jobs))
        return jobs
