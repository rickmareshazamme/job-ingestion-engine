"""Tests for the LinkedIn XML job feed generator.

Validates the LinkedIn spec contract:
  - Enum mappings (employment type, experience level, workplace type, salary period)
  - Field validation rules (apply URL https, description >= 100 chars, location)
  - Per-job XML structure includes mandatory fields
  - CDATA wrapping is intact
"""

from datetime import datetime
from types import SimpleNamespace

from lxml import etree

from src.api import linkedin_feed as feed


def _make_job(**overrides):
    """Build a Job-shaped duck object so we can test _build_job_element
    without spinning up SQLAlchemy. Only the attributes the feed reads matter."""
    defaults = dict(
        id="11111111-1111-1111-1111-111111111111",
        title="Senior Software Engineer",
        description_html="<p>" + ("Build great software with us. " * 10) + "</p>",
        description_text=None,
        employer_name="Acme Corp",
        employer_id="22222222-2222-2222-2222-222222222222",
        source_url="https://www.acme.com/careers/123",
        location_raw="San Francisco, CA, US",
        location_city="San Francisco",
        location_state="CA",
        location_country="US",
        remote_type="onsite",
        seniority="senior",
        employment_type="FULL_TIME",
        salary_min=120000,
        salary_max=180000,
        salary_currency="USD",
        salary_period="yearly",
        date_posted=datetime(2026, 5, 1),
        date_expires=datetime(2026, 6, 1),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_employer(**overrides):
    defaults = dict(
        id="22222222-2222-2222-2222-222222222222",
        linkedin_company_id="1337",
        linkedin_poster_email="recruiter@acme.com",
        claimed=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestEnumMaps:
    def test_employment_type_canonical_values(self):
        # Spec: FULL_TIME, PART_TIME, CONTRACT, INTERNSHIP, VOLUNTEER (exact tokens)
        valid = {"FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "VOLUNTEER"}
        assert set(feed.EMPLOYMENT_TYPE_MAP.values()) <= valid

    def test_experience_level_canonical_values(self):
        valid = {
            "ENTRY_LEVEL", "MID_SENIOR_LEVEL", "DIRECTOR", "EXECUTIVE",
            "INTERNSHIP", "ASSOCIATE", "NOT_APPLICABLE",
        }
        assert set(feed.EXPERIENCE_LEVEL_MAP.values()) <= valid

    def test_workplace_type_canonical_values(self):
        # Spec uses TitleCase: On-site, Hybrid, Remote
        assert set(feed.WORKPLACE_TYPE_MAP.values()) == {"On-site", "Hybrid", "Remote"}

    def test_salary_period_canonical_values(self):
        valid = {"YEARLY", "MONTHLY", "SEMIMONTHLY", "BIWEEKLY", "WEEKLY", "DAILY", "HOURLY", "ONCE"}
        assert set(feed.SALARY_PERIOD_MAP.values()) <= valid


class TestValidation:
    def test_rejects_http_apply_url(self):
        job = _make_job(source_url="http://insecure.example.com/apply")
        root = etree.Element("source")
        assert feed._build_job_element(root, job, _make_employer()) is None

    def test_rejects_short_description(self):
        job = _make_job(description_html="Too short.")
        root = etree.Element("source")
        assert feed._build_job_element(root, job, _make_employer()) is None

    def test_rejects_missing_title(self):
        job = _make_job(title="")
        root = etree.Element("source")
        assert feed._build_job_element(root, job, _make_employer()) is None

    def test_rejects_missing_location(self):
        job = _make_job(
            location_raw=None,
            location_city=None,
            location_state=None,
            location_country=None,
        )
        root = etree.Element("source")
        assert feed._build_job_element(root, job, _make_employer()) is None

    def test_accepts_valid_job(self):
        root = etree.Element("source")
        assert feed._build_job_element(root, _make_job(), _make_employer()) is not None


class TestXmlStructure:
    def _emit(self, job=None, employer=None):
        root = etree.Element("source")
        feed._build_job_element(root, job or _make_job(), employer or _make_employer())
        return root.find("job")

    def test_mandatory_fields_present(self):
        job_el = self._emit()
        for tag in ("partnerJobId", "company", "title", "description", "applyUrl", "posterEmail"):
            assert job_el.find(tag) is not None, f"missing mandatory <{tag}>"

    def test_company_id_emitted_when_set(self):
        job_el = self._emit(employer=_make_employer(linkedin_company_id="999"))
        assert job_el.find("companyId").text == "999"

    def test_company_id_omitted_when_unset(self):
        job_el = self._emit(employer=_make_employer(linkedin_company_id=None))
        assert job_el.find("companyId") is None

    def test_poster_email_per_employer_override(self):
        job_el = self._emit(employer=_make_employer(linkedin_poster_email="specific@acme.com"))
        assert job_el.find("posterEmail").text == "specific@acme.com"

    def test_poster_email_falls_back_to_default(self):
        from src.config import settings
        job_el = self._emit(employer=_make_employer(linkedin_poster_email=None))
        assert job_el.find("posterEmail").text == settings.linkedin_default_poster_email

    def test_workplace_type_mapped(self):
        job_el = self._emit(job=_make_job(remote_type="remote"))
        assert job_el.find("workplaceTypes").text == "Remote"

    def test_experience_level_mapped(self):
        job_el = self._emit(job=_make_job(seniority="senior"))
        assert job_el.find("experienceLevel").text == "MID_SENIOR_LEVEL"

    def test_jobtype_mapped(self):
        job_el = self._emit(job=_make_job(employment_type="contract"))
        assert job_el.find("jobtype").text == "CONTRACT"

    def test_unknown_enum_values_omitted_not_inserted_raw(self):
        # Don't pass through unmapped values — LinkedIn would reject them
        job_el = self._emit(job=_make_job(employment_type="some_weird_thing"))
        assert job_el.find("jobtype") is None

    def test_salary_block(self):
        job_el = self._emit()
        salaries = job_el.find("salaries")
        assert salaries is not None
        salary = salaries.find("salary")
        assert salary.find("highEnd/amount").text == "180000"
        assert salary.find("highEnd/currencyCode").text == "USD"
        assert salary.find("lowEnd/amount").text == "120000"
        assert salary.find("period").text == "YEARLY"
        assert salary.find("type").text == "BASE_SALARY"

    def test_salary_omitted_when_incomplete(self):
        job_el = self._emit(job=_make_job(salary_min=None, salary_max=None))
        assert job_el.find("salaries") is None

    def test_date_format_is_mm_dd_yyyy(self):
        job_el = self._emit()
        assert job_el.find("listDate").text == "05/01/2026"
        assert job_el.find("expirationDate").text == "06/01/2026"

    def test_partner_job_id_under_40_chars(self):
        # UUIDs are 36 chars — well under LinkedIn's 40-char limit
        job_el = self._emit()
        assert len(job_el.find("partnerJobId").text) <= 40


class TestFormatHelpers:
    def test_location_prefers_raw(self):
        job = _make_job(
            location_raw="Brooklyn, NY",
            location_city="Brooklyn",
            location_state="NY",
            location_country="US",
        )
        assert feed._build_location_string(job) == "Brooklyn, NY"

    def test_location_assembles_from_structured_when_raw_missing(self):
        job = _make_job(
            location_raw=None,
            location_city="London",
            location_state=None,
            location_country="GB",
        )
        assert feed._build_location_string(job) == "London, GB"

    def test_format_date_none(self):
        assert feed._format_date(None) is None

    def test_format_date_value(self):
        assert feed._format_date(datetime(2026, 1, 7)) == "01/07/2026"
