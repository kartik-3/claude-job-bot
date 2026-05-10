from scrapers.amazon import AmazonScraper
from scrapers.ashby import AshbyScraper
from scrapers.base import BaseScraper, Company, Job
from scrapers.eightfold import EightfoldScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.icims import IcimsScraper
from scrapers.lever import LeverScraper
from scrapers.oracle import OracleScraper
from scrapers.smartrecruiters import SmartRecruitersScraper
from scrapers.successfactors import SuccessFactorsScraper
from scrapers.workable import WorkableScraper
from scrapers.workday import WorkdayScraper
from scrapers.workday_browser import WorkdayBrowserScraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "workday": WorkdayScraper,
    "workday_browser": WorkdayBrowserScraper,
    "amazon": AmazonScraper,
    "oracle": OracleScraper,
    "eightfold": EightfoldScraper,
    "icims": IcimsScraper,
    "smartrecruiters": SmartRecruitersScraper,
    "workable": WorkableScraper,
    "successfactors": SuccessFactorsScraper,
}

__all__ = ["Company", "Job", "get_scraper"]


def get_scraper(ats: str) -> BaseScraper | None:
    cls = _REGISTRY.get(ats)
    return cls() if cls else None
