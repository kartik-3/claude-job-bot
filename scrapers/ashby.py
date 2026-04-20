import logging

from scrapers.base import BaseScraper, Company, Job

logger = logging.getLogger(__name__)

_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        # Phase 1
        raise NotImplementedError
