import logging

from scrapers.base import BaseScraper, Company, Job

logger = logging.getLogger(__name__)

_API = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverScraper(BaseScraper):
    def fetch_jobs(self, company: Company) -> list[Job]:
        # Phase 1
        raise NotImplementedError
