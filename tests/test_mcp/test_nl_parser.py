"""Tests for natural language query parser."""

import pytest

from src.mcp_server.nl_parser import parse_natural_language


class TestRemoteDetection:
    def test_remote_keyword(self):
        result = parse_natural_language("remote Python jobs")
        assert result.is_remote is True
        assert "python" in result.keywords.lower()

    def test_hybrid(self):
        result = parse_natural_language("hybrid engineer in London")
        assert result.is_remote is True
        assert result.remote_type == "hybrid"

    def test_no_remote(self):
        result = parse_natural_language("Python developer in NYC")
        assert result.is_remote is None


class TestSalaryParsing:
    def test_over_100k(self):
        result = parse_natural_language("jobs paying over 100k")
        assert result.salary_min == 100000

    def test_salary_range(self):
        result = parse_natural_language("developer 120k-150k")
        assert result.salary_min == 120000
        assert result.salary_max == 150000

    def test_currency_eur(self):
        result = parse_natural_language("jobs paying over 80k EUR")
        assert result.salary_min == 80000
        assert result.salary_currency == "EUR"

    def test_currency_gbp(self):
        result = parse_natural_language("engineer 60k GBP")
        assert result.salary_currency == "GBP"

    def test_under_salary(self):
        result = parse_natural_language("jobs under 200k")
        assert result.salary_max == 200000


class TestLocationParsing:
    def test_country_us(self):
        result = parse_natural_language("engineer in USA")
        assert result.country == "US"

    def test_country_australia(self):
        result = parse_natural_language("developer in Australia")
        assert result.country == "AU"

    def test_city_san_francisco(self):
        result = parse_natural_language("engineer in San Francisco")
        assert result.city == "San Francisco"

    def test_city_london(self):
        result = parse_natural_language("marketing jobs in London")
        assert result.city == "London"

    def test_city_nyc(self):
        result = parse_natural_language("developer in NYC")
        assert result.city == "New York"

    def test_country_germany(self):
        result = parse_natural_language("engineer in Germany")
        assert result.country == "DE"


class TestSeniorityParsing:
    def test_senior(self):
        result = parse_natural_language("senior software engineer")
        assert result.seniority == "senior"

    def test_junior(self):
        result = parse_natural_language("junior developer")
        assert result.seniority == "junior"

    def test_entry_level(self):
        result = parse_natural_language("entry level analyst")
        assert result.seniority == "junior"

    def test_lead(self):
        result = parse_natural_language("lead engineer")
        assert result.seniority == "lead"

    def test_principal(self):
        result = parse_natural_language("staff engineer roles")
        assert result.seniority == "principal"


class TestEmploymentType:
    def test_full_time(self):
        result = parse_natural_language("full-time developer")
        assert result.employment_type == "FULL_TIME"

    def test_contract(self):
        result = parse_natural_language("contract DevOps engineer")
        assert result.employment_type == "CONTRACTOR"

    def test_part_time(self):
        result = parse_natural_language("part-time marketing")
        assert result.employment_type == "PART_TIME"


class TestEmployerParsing:
    def test_at_company(self):
        result = parse_natural_language("engineer at google")
        assert result.employer == "google"

    def test_at_company_with_location(self):
        result = parse_natural_language("developer at stripe in SF")
        assert result.employer == "stripe"


class TestComplexQueries:
    def test_full_query(self):
        result = parse_natural_language(
            "remote senior Python developer paying over 150k USD"
        )
        assert result.is_remote is True
        assert result.seniority == "senior"
        assert result.salary_min == 150000
        assert result.salary_currency == "USD"
        assert "python" in result.keywords.lower()

    def test_location_and_salary(self):
        result = parse_natural_language(
            "data engineer in Australia AUD 120k-150k"
        )
        assert result.country == "AU"
        assert result.salary_min == 120000
        assert result.salary_max == 150000
        assert result.salary_currency == "AUD"

    def test_contract_with_location(self):
        result = parse_natural_language(
            "contract DevOps engineer in Berlin"
        )
        assert result.employment_type == "CONTRACTOR"
        assert result.city == "Berlin"

    def test_empty_query(self):
        result = parse_natural_language("")
        assert result.keywords == ""
        assert result.country is None

    def test_simple_keyword(self):
        result = parse_natural_language("python")
        assert "python" in result.keywords.lower()
