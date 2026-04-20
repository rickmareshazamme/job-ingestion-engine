"""Tests for classification module."""

import pytest

from src.normalizer.classification import (
    classify_categories,
    classify_employment_type,
    detect_remote,
    detect_seniority,
)


class TestEmploymentType:
    def test_full_time(self):
        assert classify_employment_type("Full-Time") == "FULL_TIME"
        assert classify_employment_type("permanent") == "FULL_TIME"
        assert classify_employment_type("Regular") == "FULL_TIME"

    def test_part_time(self):
        assert classify_employment_type("Part-Time") == "PART_TIME"
        assert classify_employment_type("part time") == "PART_TIME"

    def test_contract(self):
        assert classify_employment_type("Contract") == "CONTRACTOR"
        assert classify_employment_type("Freelance") == "CONTRACTOR"

    def test_temporary(self):
        assert classify_employment_type("Temporary") == "TEMPORARY"
        assert classify_employment_type("Casual") == "TEMPORARY"

    def test_intern(self):
        assert classify_employment_type("Internship") == "INTERN"
        assert classify_employment_type("co-op") == "INTERN"

    def test_default(self):
        assert classify_employment_type(None) == "FULL_TIME"
        assert classify_employment_type("") == "FULL_TIME"
        assert classify_employment_type("unknown") == "FULL_TIME"


class TestSeniority:
    def test_senior(self):
        assert detect_seniority("Senior Software Engineer") == "senior"
        assert detect_seniority("Sr. Developer") == "senior"

    def test_junior(self):
        assert detect_seniority("Junior Developer") == "junior"
        assert detect_seniority("Entry Level Analyst") == "junior"
        assert detect_seniority("Graduate Engineer") == "junior"

    def test_lead(self):
        assert detect_seniority("Tech Lead") == "lead"
        assert detect_seniority("Engineering Lead") == "lead"

    def test_principal(self):
        assert detect_seniority("Principal Engineer") == "principal"
        assert detect_seniority("Staff Engineer") == "principal"

    def test_executive(self):
        assert detect_seniority("Chief Technology Officer") == "executive"
        assert detect_seniority("VP of Engineering") == "executive"

    def test_director(self):
        assert detect_seniority("Director of Engineering") == "director"

    def test_default_mid(self):
        assert detect_seniority("Software Engineer") == "mid"

    def test_intern(self):
        assert detect_seniority("Software Engineering Intern") == "intern"


class TestCategories:
    def test_engineering(self):
        cats = classify_categories("Software Engineer")
        assert "Engineering" in cats

    def test_data(self):
        cats = classify_categories("Data Scientist")
        assert "Data & Analytics" in cats

    def test_design(self):
        cats = classify_categories("UX Designer")
        assert "Design" in cats

    def test_product(self):
        cats = classify_categories("Product Manager")
        assert "Product" in cats

    def test_marketing(self):
        cats = classify_categories("Marketing Manager")
        assert "Marketing" in cats

    def test_unknown(self):
        cats = classify_categories("Chief Happiness Officer")
        assert cats == ["Other"]


class TestRemoteDetection:
    def test_remote_in_title(self):
        is_remote, rtype = detect_remote("Senior Engineer (Remote)")
        assert is_remote is True
        assert rtype == "remote"

    def test_hybrid_in_title(self):
        is_remote, rtype = detect_remote("Software Engineer - Hybrid")
        assert is_remote is True
        assert rtype == "hybrid"

    def test_onsite(self):
        is_remote, rtype = detect_remote("Software Engineer")
        assert is_remote is False
        assert rtype == "onsite"

    def test_remote_in_location(self):
        is_remote, rtype = detect_remote("Engineer", location="Remote - US")
        assert is_remote is True

    def test_wfh_in_description(self):
        is_remote, rtype = detect_remote("Engineer", description="This role allows work from home flexibility")
        assert is_remote is True
