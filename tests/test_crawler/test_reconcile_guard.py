"""Tests for the feed-snapshot reconciliation truncation guard.

The guard decides whether a Shazamme feed pull is complete enough to safely
expire jobs missing from it. A short/truncated pull must NOT trigger mass
expiry of live jobs (see the job-index deep-offset truncation bug).
"""

from src.tasks.crawl import _should_reconcile


def test_reconciles_when_no_prior_baseline():
    # First-ever pull has no baseline to compare against — allow it.
    assert _should_reconcile(prev_count=0, curr_count=9278, min_ratio=0.8) is True


def test_reconciles_on_healthy_full_pull():
    assert _should_reconcile(prev_count=9278, curr_count=9300, min_ratio=0.8) is True


def test_reconciles_on_minor_shrink_within_threshold():
    # 9278 -> 8000 is an 86% pull, above the 80% floor: still reconcile.
    assert _should_reconcile(prev_count=9278, curr_count=8000, min_ratio=0.8) is True


def test_skips_on_truncated_pull():
    # The classic flap: 9278 -> 6000 (~65%) is a suspected truncation.
    assert _should_reconcile(prev_count=9278, curr_count=6000, min_ratio=0.8) is False


def test_skips_on_empty_pull():
    assert _should_reconcile(prev_count=9278, curr_count=0, min_ratio=0.8) is False


def test_exact_threshold_boundary_reconciles():
    # curr == prev * ratio is allowed (>=).
    assert _should_reconcile(prev_count=1000, curr_count=800, min_ratio=0.8) is True
