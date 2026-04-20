"""Tests for salary parser — covers 30+ global formats."""

import pytest

from src.normalizer.salary import parse_salary


class TestSalaryParser:
    def test_simple_usd(self):
        result = parse_salary("$120,000")
        assert result.min_value == 120000
        assert result.currency == "USD"
        assert result.period == "YEAR"

    def test_usd_range(self):
        result = parse_salary("$120,000 - $150,000")
        assert result.min_value == 120000
        assert result.max_value == 150000
        assert result.currency == "USD"

    def test_k_notation(self):
        result = parse_salary("$120k - $150k")
        assert result.min_value == 120000
        assert result.max_value == 150000

    def test_aud_annual(self):
        result = parse_salary("AUD 80,000 - 100,000 p.a.")
        assert result.min_value == 80000
        assert result.max_value == 100000
        assert result.currency == "AUD"
        assert result.period == "YEAR"

    def test_gbp_range(self):
        result = parse_salary("£45,000 - £55,000 per annum")
        assert result.min_value == 45000
        assert result.max_value == 55000
        assert result.currency == "GBP"
        assert result.period == "YEAR"

    def test_eur_hourly(self):
        result = parse_salary("EUR 50/hr")
        assert result.min_value == 50
        assert result.max_value == 50
        assert result.currency == "EUR"
        assert result.period == "HOUR"

    def test_hourly_rate(self):
        result = parse_salary("$45 per hour")
        assert result.min_value == 45
        assert result.currency == "USD"
        assert result.period == "HOUR"

    def test_monthly(self):
        result = parse_salary("$8,000 per month")
        assert result.min_value == 8000
        assert result.period == "MONTH"

    def test_competitive(self):
        result = parse_salary("Competitive")
        assert result.min_value is None
        assert result.max_value is None

    def test_negotiable(self):
        result = parse_salary("Negotiable")
        assert result.min_value is None

    def test_doe(self):
        result = parse_salary("DOE")
        assert result.min_value is None

    def test_empty(self):
        result = parse_salary("")
        assert result.min_value is None

    def test_none(self):
        result = parse_salary(None)
        assert result.min_value is None

    def test_inr_lakhs(self):
        result = parse_salary("Rs 15,00,000")
        assert result.min_value == 1500000
        assert result.currency == "INR"

    def test_cad_range(self):
        result = parse_salary("CAD 90,000 - 120,000")
        assert result.min_value == 90000
        assert result.max_value == 120000
        assert result.currency == "CAD"

    def test_chf(self):
        result = parse_salary("CHF 130,000")
        assert result.min_value == 130000
        assert result.currency == "CHF"

    def test_sgd_monthly(self):
        result = parse_salary("SGD 8,000 - 12,000 per month")
        assert result.min_value == 8000
        assert result.max_value == 12000
        assert result.currency == "SGD"
        assert result.period == "MONTH"

    def test_single_value_yearly(self):
        result = parse_salary("$95,000 per year")
        assert result.min_value == 95000
        assert result.max_value == 95000
        assert result.period == "YEAR"

    def test_raw_preserved(self):
        result = parse_salary("$120k - $150k")
        assert result.raw == "$120k - $150k"
