import logging

from scrapers.base import BaseScraper, Company, Job

logger = logging.getLogger(__name__)

_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        # Phase 1
        raise NotImplementedError
