import logging

from scrapers.base import BaseScraper, Company, Job

logger = logging.getLogger(__name__)


class WorkdayScraper(BaseScraper):
    """Discovery only — Workday applications require auth and go to manual queue."""

    def fetch_jobs(self, company: Company) -> list[Job]:
        # Phase 1 stretch
        raise NotImplementedError
