import hashlib
from abc import ABC, abstractmethod

from pydantic import BaseModel


class Company(BaseModel):
    name: str
    ats: str
    slug: str | None = None


class Job(BaseModel):
    id: str
    company: str
    title: str
    url: str
    apply_url: str | None = None
    ats: str
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    posted_at: str | None = None


class BaseScraper(ABC):
    @abstractmethod
    def fetch_jobs(self, company: Company) -> list[Job]: ...


def make_job_id(company: str, title: str, url: str) -> str:
    return hashlib.sha256(f"{company}:{title}:{url}".encode()).hexdigest()
