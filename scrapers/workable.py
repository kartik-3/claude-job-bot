"""Workable job board scraper (browser-based).

Workable's career site (apply.workable.com/{shortcode}/) is a React SPA
protected by Cloudflare JS challenge — direct HTTP requests are blocked.
Strategy (mirrors workday_browser.py):
  1. Load the careers page in Chromium to pass the JS challenge.
  2. Capture the account UUID from the page's first API response.
  3. Paginate via page.evaluate() GET requests inside the browser context.

Slug format in sources.yaml:
    {shortcode}

Examples:
    huggingface
    innovaccer-analytics
    covergo

How to find the shortcode for any company:
    Visit apply.workable.com/{shortcode}/ — the shortcode is the path segment.
    It can also appear as a subdomain: {shortcode}.workable.com (use same value).
"""
import logging
import re

from scrapers.base import BaseScraper, Company, Job, make_job_id

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


def _parse_workable_date(created_at: str | None) -> str | None:
    """Return ISO-8601 date (YYYY-MM-DD) from Workable's ISO timestamp, or None."""
    if not created_at:
        return None
    try:
        from datetime import datetime
        return (
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            .date()
            .isoformat()
        )
    except (ValueError, AttributeError):
        return None


class WorkableScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        from playwright.sync_api import sync_playwright

        shortcode = (company.slug or "").strip()
        if not shortcode:
            raise ValueError(f"Workable shortcode required, got: {shortcode!r}")

        careers_url = f"https://apply.workable.com/{shortcode}/"

        captured: dict = {"uuid": None, "first_jobs": None}

        # JS run inside browser to fetch one page of jobs via the Workable API.
        # We use XMLHttpRequest so page scripts (analytics etc.) can't interfere.
        fetch_js = """
        async ([url]) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.setRequestHeader('Accept', 'application/json');
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
                # Capture the account UUID from any widget/accounts API response
                m = re.search(r"/accounts/([0-9a-f-]{36})/jobs", response.url)
                if m and captured["uuid"] is None:
                    captured["uuid"] = m.group(1)
                    try:
                        captured["first_jobs"] = response.json()
                    except Exception:
                        pass

            page.on("response", on_response)

            logger.debug("workable/%s: loading %s", shortcode, careers_url)
            page.goto(careers_url, wait_until="networkidle", timeout=60_000)

            # Fall back to reading UUID from the page meta tag if XHR wasn't intercepted
            if not captured["uuid"]:
                meta = page.query_selector('meta[name="account"]')
                if meta:
                    captured["uuid"] = meta.get_attribute("content")

            uuid = captured["uuid"]
            if not uuid:
                logger.error("workable/%s: could not determine account UUID", shortcode)
                browser.close()
                return []

            logger.debug("workable/%s: account UUID = %s", shortcode, uuid)

            def fetch_page(p: int) -> dict | None:
                if p == 0 and captured["first_jobs"]:
                    return captured["first_jobs"]
                url = (
                    f"https://apply.workable.com/api/v1/widget/accounts/{uuid}/jobs"
                    f"?details=true&count={_PAGE_SIZE}&page={p}"
                )
                result = page.evaluate(fetch_js, [url])
                if isinstance(result, dict) and "error" in result:
                    logger.error(
                        "workable/%s: fetch error %s on page %d",
                        shortcode, result["error"], p,
                    )
                    return None
                return result

            page_num = 0
            total_pages = None

            while True:
                data = fetch_page(page_num)
                if not data:
                    break

                results = data.get("results", [])
                if not results:
                    break

                if total_pages is None:
                    # Workable paginates by page count, not offset
                    count = data.get("count", len(results))
                    per_page = _PAGE_SIZE
                    total_pages = -(-count // per_page)  # ceiling div

                for item in results:
                    title = item.get("title", "")
                    job_code = item.get("shortcode", "")
                    apply_url = f"https://apply.workable.com/{shortcode}/j/{job_code}/"
                    city = item.get("city") or ""
                    country = item.get("country") or ""
                    location = ", ".join(p for p in [city, country] if p) or None
                    remote = item.get("remote", False)
                    posted_at = _parse_workable_date(item.get("created_at"))

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

                page_num += 1
                if total_pages is not None and page_num >= total_pages:
                    break

            browser.close()

        logger.debug("workable/%s: fetched %d jobs", shortcode, len(jobs))
        return jobs
