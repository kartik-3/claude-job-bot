from scrapers.amazon import AmazonScraper
from scrapers.ashby import AshbyScraper
from scrapers.base import BaseScraper, Company, Job
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from scrapers.workday import WorkdayScraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "workday": WorkdayScraper,
    "amazon": AmazonScraper,
}

__all__ = ["Company", "Job", "get_scraper"]


def get_scraper(ats: str) -> BaseScraper | None:
    cls = _REGISTRY.get(ats)
    return cls() if cls else None
