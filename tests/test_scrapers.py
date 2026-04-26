import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrapers.base import Company, make_job_id
from scrapers.amazon import AmazonScraper
from scrapers.ashby import AshbyScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from scrapers.oracle import OracleScraper

FIXTURES = Path(__file__).parent / "fixtures"


def _mock_get(payload: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def anthropic():
    return Company(name="Anthropic", ats="greenhouse", slug="anthropic")


@pytest.fixture
def linear():
    return Company(name="Linear", ats="lever", slug="linear")


@pytest.fixture
def figma():
    return Company(name="Figma", ats="ashby", slug="figma")


# --- Greenhouse ---

class TestGreenhouseScraper:
    def test_parses_job_count(self, anthropic):
        payload = json.loads((FIXTURES / "greenhouse_response.json").read_text())
        with patch("scrapers.greenhouse.requests.get", return_value=_mock_get(payload)):
            jobs = GreenhouseScraper().fetch_jobs(anthropic)
        assert len(jobs) == 2

    def test_job_fields(self, anthropic):
        payload = json.loads((FIXTURES / "greenhouse_response.json").read_text())
        with patch("scrapers.greenhouse.requests.get", return_value=_mock_get(payload)):
            jobs = GreenhouseScraper().fetch_jobs(anthropic)
        job = jobs[0]
        assert job.company == "Anthropic"
        assert job.ats == "greenhouse"
        assert job.title == "Senior Software Engineer, Core Product"
        assert job.url == "https://boards.greenhouse.io/anthropic/jobs/4028988007"
        assert job.location == "San Francisco, CA"
        assert job.remote is False
        assert job.posted_at == "2026-04-01T10:00:00-07:00"

    def test_remote_detection(self, anthropic):
        payload = json.loads((FIXTURES / "greenhouse_response.json").read_text())
        with patch("scrapers.greenhouse.requests.get", return_value=_mock_get(payload)):
            jobs = GreenhouseScraper().fetch_jobs(anthropic)
        remote_job = jobs[1]
        assert remote_job.location == "Remote"
        assert remote_job.remote is True

    def test_id_is_deterministic(self, anthropic):
        payload = json.loads((FIXTURES / "greenhouse_response.json").read_text())
        with patch("scrapers.greenhouse.requests.get", return_value=_mock_get(payload)):
            jobs1 = GreenhouseScraper().fetch_jobs(anthropic)
            jobs2 = GreenhouseScraper().fetch_jobs(anthropic)
        assert jobs1[0].id == jobs2[0].id

    def test_empty_response(self, anthropic):
        with patch("scrapers.greenhouse.requests.get", return_value=_mock_get({"jobs": [], "meta": {"total": 0}})):
            jobs = GreenhouseScraper().fetch_jobs(anthropic)
        assert jobs == []


# --- Lever ---

class TestLeverScraper:
    def test_parses_job_count(self, linear):
        payload = json.loads((FIXTURES / "lever_response.json").read_text())
        with patch("scrapers.lever.requests.get", return_value=_mock_get(payload)):
            jobs = LeverScraper().fetch_jobs(linear)
        assert len(jobs) == 2

    def test_job_fields(self, linear):
        payload = json.loads((FIXTURES / "lever_response.json").read_text())
        with patch("scrapers.lever.requests.get", return_value=_mock_get(payload)):
            jobs = LeverScraper().fetch_jobs(linear)
        job = jobs[0]
        assert job.company == "Linear"
        assert job.ats == "lever"
        assert job.title == "Senior Software Engineer"
        assert job.url == "https://jobs.lever.co/linear/abc123-def456-7890"
        assert job.apply_url == "https://jobs.lever.co/linear/abc123-def456-7890/apply"
        assert job.location == "San Francisco or Remote"
        assert job.remote is True
        assert job.posted_at is not None

    def test_posted_at_conversion(self, linear):
        payload = json.loads((FIXTURES / "lever_response.json").read_text())
        with patch("scrapers.lever.requests.get", return_value=_mock_get(payload)):
            jobs = LeverScraper().fetch_jobs(linear)
        # createdAt 1743465600000 ms → ISO 8601 string
        assert "2025" in jobs[0].posted_at or "2026" in jobs[0].posted_at
        assert "T" in jobs[0].posted_at

    def test_empty_response(self, linear):
        with patch("scrapers.lever.requests.get", return_value=_mock_get([])):
            jobs = LeverScraper().fetch_jobs(linear)
        assert jobs == []


# --- Ashby ---

class TestAshbyScraper:
    def test_parses_job_count(self, figma):
        payload = json.loads((FIXTURES / "ashby_response.json").read_text())
        with patch("scrapers.ashby.requests.get", return_value=_mock_get(payload)):
            jobs = AshbyScraper().fetch_jobs(figma)
        assert len(jobs) == 2

    def test_job_fields(self, figma):
        payload = json.loads((FIXTURES / "ashby_response.json").read_text())
        with patch("scrapers.ashby.requests.get", return_value=_mock_get(payload)):
            jobs = AshbyScraper().fetch_jobs(figma)
        job = jobs[0]
        assert job.company == "Figma"
        assert job.ats == "ashby"
        assert job.title == "Senior Software Engineer"
        assert job.url == "https://jobs.ashbyhq.com/figma/uuid-1234-abcd"
        assert job.location == "San Francisco, CA"
        assert job.remote is False
        assert job.posted_at == "2026-04-01"

    def test_explicit_remote_flag(self, figma):
        payload = json.loads((FIXTURES / "ashby_response.json").read_text())
        with patch("scrapers.ashby.requests.get", return_value=_mock_get(payload)):
            jobs = AshbyScraper().fetch_jobs(figma)
        assert jobs[1].remote is True

    def test_empty_response(self, figma):
        with patch("scrapers.ashby.requests.get", return_value=_mock_get({"jobPostings": []})):
            jobs = AshbyScraper().fetch_jobs(figma)
        assert jobs == []


# --- Amazon ---

@pytest.fixture
def amazon():
    return Company(name="Amazon", ats="amazon", slug="USA")


class TestAmazonScraper:
    def test_parses_job_count(self, amazon):
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)):
            jobs = AmazonScraper().fetch_jobs(amazon)
        assert len(jobs) == 2

    def test_job_fields(self, amazon):
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)):
            jobs = AmazonScraper().fetch_jobs(amazon)
        job = jobs[0]
        assert job.company == "Amazon"
        assert job.ats == "amazon"
        assert job.title == "Software Development Engineer, Prime Video"
        assert job.url == "https://www.amazon.jobs/en/jobs/10403410/software-development-engineer-prime-video"
        assert job.apply_url == "https://account.amazon.com/jobs/10403410/apply"
        assert job.location == "US, WA, Seattle"
        assert job.remote is False
        assert job.posted_at == "2026-04-25"

    def test_remote_detection(self, amazon):
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)):
            jobs = AmazonScraper().fetch_jobs(amazon)
        remote_job = jobs[1]
        assert remote_job.location == "Remote"
        assert remote_job.remote is True

    def test_date_parsing(self, amazon):
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)):
            jobs = AmazonScraper().fetch_jobs(amazon)
        assert jobs[0].posted_at == "2026-04-25"
        assert jobs[1].posted_at == "2026-04-20"

    def test_id_is_deterministic(self, amazon):
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)):
            jobs1 = AmazonScraper().fetch_jobs(amazon)
            jobs2 = AmazonScraper().fetch_jobs(amazon)
        assert jobs1[0].id == jobs2[0].id

    def test_empty_response(self, amazon):
        with patch("scrapers.amazon.requests.get", return_value=_mock_get({"hits": 0, "jobs": []})):
            jobs = AmazonScraper().fetch_jobs(amazon)
        assert jobs == []

    def test_invalid_slug_raises(self):
        # A slug with only commas/spaces produces no valid country codes
        company = Company(name="Amazon", ats="amazon", slug=" , , ")
        with pytest.raises(ValueError, match="comma-separated country codes"):
            AmazonScraper().fetch_jobs(company)

    def test_multi_country_slug(self, amazon):
        company = Company(name="Amazon", ats="amazon", slug="USA,IND")
        payload = json.loads((FIXTURES / "amazon_response.json").read_text())
        with patch("scrapers.amazon.requests.get", return_value=_mock_get(payload)) as mock_get:
            AmazonScraper().fetch_jobs(company)
        call_params = mock_get.call_args
        # params is a list of tuples; both country codes should be present
        params = call_params[1]["params"]
        country_params = [v for k, v in params if k == "normalized_country_code[]"]
        assert "USA" in country_params
        assert "IND" in country_params


# --- Oracle ---

@pytest.fixture
def jpmc():
    return Company(name="JP Morgan", ats="oracle", slug="jpmc/CX_1001")


class TestOracleScraper:
    def test_parses_job_count(self, jpmc):
        payload = json.loads((FIXTURES / "oracle_response.json").read_text())
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)):
            jobs = OracleScraper().fetch_jobs(jpmc)
        assert len(jobs) == 2

    def test_job_fields(self, jpmc):
        payload = json.loads((FIXTURES / "oracle_response.json").read_text())
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)):
            jobs = OracleScraper().fetch_jobs(jpmc)
        job = jobs[0]
        assert job.company == "JP Morgan"
        assert job.ats == "oracle"
        assert job.title == "Software Engineer III"
        assert job.url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210601531"
        assert job.apply_url == job.url
        assert job.location == "New York, NY, United States"
        assert job.remote is None
        assert job.posted_at == "2026-04-22"

    def test_remote_detection(self, jpmc):
        payload = json.loads((FIXTURES / "oracle_response.json").read_text())
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)):
            jobs = OracleScraper().fetch_jobs(jpmc)
        assert jobs[1].remote is True
        assert jobs[1].location == "Remote"

    def test_id_is_deterministic(self, jpmc):
        payload = json.loads((FIXTURES / "oracle_response.json").read_text())
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)):
            jobs1 = OracleScraper().fetch_jobs(jpmc)
            jobs2 = OracleScraper().fetch_jobs(jpmc)
        assert jobs1[0].id == jobs2[0].id

    def test_empty_response(self, jpmc):
        payload = {"items": [{"TotalJobsCount": 0, "requisitionList": []}], "count": 1}
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)):
            jobs = OracleScraper().fetch_jobs(jpmc)
        assert jobs == []

    def test_invalid_slug_raises(self):
        company = Company(name="Test", ats="oracle", slug="no-slash-here")
        with pytest.raises(ValueError, match="tenant/siteNumber"):
            OracleScraper().fetch_jobs(company)

    def test_regional_host(self):
        company = Company(name="Oracle", ats="oracle", slug="eeho.us2/CX_45001")
        payload = json.loads((FIXTURES / "oracle_response.json").read_text())
        with patch("scrapers.oracle.requests.get", return_value=_mock_get(payload)) as mock_get:
            jobs = OracleScraper().fetch_jobs(company)
        url = mock_get.call_args[0][0]
        assert "eeho.fa.us2.oraclecloud.com" in url
        assert jobs[0].url.startswith("https://eeho.fa.us2.oraclecloud.com")


# --- Shared ---

def test_make_job_id_is_deterministic():
    id1 = make_job_id("Acme", "Engineer", "https://example.com/job/1")
    id2 = make_job_id("Acme", "Engineer", "https://example.com/job/1")
    assert id1 == id2


def test_make_job_id_differs_on_url():
    id1 = make_job_id("Acme", "Engineer", "https://example.com/job/1")
    id2 = make_job_id("Acme", "Engineer", "https://example.com/job/2")
    assert id1 != id2
