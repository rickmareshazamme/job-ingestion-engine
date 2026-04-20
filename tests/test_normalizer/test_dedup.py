"""Tests for deduplication engine."""

import pytest

from src.normalizer.dedup import generate_content_hash, titles_match_fuzzy


class TestContentHash:
    def test_same_job_same_hash(self):
        h1 = generate_content_hash("Software Engineer", "acme.com", "US", "San Francisco")
        h2 = generate_content_hash("Software Engineer", "acme.com", "US", "San Francisco")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = generate_content_hash("Software Engineer", "ACME.com", "us", "San Francisco")
        h2 = generate_content_hash("software engineer", "acme.com", "US", "san francisco")
        assert h1 == h2

    def test_different_title(self):
        h1 = generate_content_hash("Software Engineer", "acme.com", "US", "SF")
        h2 = generate_content_hash("Data Scientist", "acme.com", "US", "SF")
        assert h1 != h2

    def test_different_employer(self):
        h1 = generate_content_hash("Software Engineer", "acme.com", "US", "SF")
        h2 = generate_content_hash("Software Engineer", "other.com", "US", "SF")
        assert h1 != h2

    def test_different_country(self):
        h1 = generate_content_hash("Software Engineer", "acme.com", "US", "London")
        h2 = generate_content_hash("Software Engineer", "acme.com", "GB", "London")
        assert h1 != h2


class TestFuzzyMatch:
    def test_exact_match(self):
        assert titles_match_fuzzy("Software Engineer", "Software Engineer") is True

    def test_minor_difference(self):
        assert titles_match_fuzzy("Senior Software Engineer", "Sr. Software Engineer") is True

    def test_very_different(self):
        assert titles_match_fuzzy("Software Engineer", "Marketing Manager") is False

    def test_empty_strings(self):
        assert titles_match_fuzzy("", "") is True

    def test_case_insensitive(self):
        assert titles_match_fuzzy("SOFTWARE ENGINEER", "software engineer") is True
