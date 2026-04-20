"""Tests for location parser."""

import pytest

from src.normalizer.location import parse_location


class TestLocationParser:
    def test_us_city_state(self):
        result = parse_location("San Francisco, CA")
        assert result.city == "San Francisco"
        assert result.state == "CA"
        assert result.country == "US"

    def test_us_city_state_country(self):
        result = parse_location("New York, NY, United States")
        assert result.city == "New York"
        assert result.state == "NY"
        assert result.country == "US"

    def test_au_city_state(self):
        result = parse_location("Sydney, NSW, Australia")
        assert result.city == "Sydney"
        assert result.state == "NSW"
        assert result.country == "AU"

    def test_au_state_only(self):
        result = parse_location("Melbourne, VIC")
        assert result.city == "Melbourne"
        assert result.state == "VIC"
        assert result.country == "AU"

    def test_uk_city(self):
        result = parse_location("London, United Kingdom")
        assert result.city == "London"
        assert result.country == "GB"

    def test_remote_only(self):
        result = parse_location("Remote")
        assert result.is_remote is True
        assert result.remote_type == "remote"

    def test_hybrid(self):
        result = parse_location("Hybrid - San Francisco, CA")
        assert result.is_remote is True
        assert result.remote_type == "hybrid"
        assert result.city == "San Francisco"

    def test_remote_with_location(self):
        result = parse_location("Remote - US")
        assert result.is_remote is True
        assert result.country == "US"

    def test_country_code_only(self):
        result = parse_location("DE")
        assert result.country == "DE"

    def test_full_country_name(self):
        result = parse_location("Germany")
        assert result.country == "DE"

    def test_city_country(self):
        result = parse_location("Berlin, Germany")
        assert result.city == "Berlin"
        assert result.country == "DE"

    def test_empty(self):
        result = parse_location("")
        assert result.city is None
        assert result.country == ""

    def test_none_input(self):
        result = parse_location(None)
        assert result.city is None

    def test_work_from_home(self):
        result = parse_location("Work from Home")
        assert result.is_remote is True

    def test_singapore(self):
        result = parse_location("Singapore")
        assert result.country == "SG"

    def test_us_full_state_name(self):
        result = parse_location("Austin, Texas")
        assert result.city == "Austin"
        assert result.state == "TX"
        assert result.country == "US"

    def test_multiple_locations_pipe(self):
        result = parse_location("San Francisco | New York")
        assert result.city == "San Francisco"

    def test_tokyo_japan(self):
        result = parse_location("Tokyo, Japan")
        assert result.city == "Tokyo"
        assert result.country == "JP"
