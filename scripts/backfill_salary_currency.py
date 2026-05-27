"""Backfill salary_currency for rows that were tagged USD by default.

Earlier versions of the salary parser defaulted to USD whenever the raw
salary string lacked a currency symbol. That tagged AU/NZ/GB/EU jobs as USD
even when the original posting was in local currency.

This script rewrites salary_currency to the country-derived currency for
rows where:
  - salary_min is not null (so a currency is actually rendered)
  - salary_currency is null OR currently 'USD'
  - location_country is in our COUNTRY_TO_CURRENCY map
  - the raw salary string does NOT explicitly mention USD/$
    (so we don't clobber genuine USD postings for AU employers etc.)

Idempotent and safe to re-run.
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from src.config import settings
from src.normalizer.salary import COUNTRY_TO_CURRENCY


def main() -> int:
    engine = create_engine(settings.database_url_sync)
    total = 0
    with engine.begin() as conn:
        for country_iso, currency in COUNTRY_TO_CURRENCY.items():
            if currency == "USD":
                continue
            result = conn.execute(
                text("""
                    UPDATE jobs
                    SET salary_currency = :cur
                    WHERE location_country = :iso
                      AND salary_min IS NOT NULL
                      AND (salary_currency IS NULL OR salary_currency = 'USD')
                      AND COALESCE(salary_raw, '') NOT ILIKE '%usd%'
                      AND COALESCE(salary_raw, '') NOT LIKE '%$%'
                """),
                {"cur": currency, "iso": country_iso},
            )
            if result.rowcount:
                print(
                    f"backfill_salary_currency: {country_iso} -> {currency}: "
                    f"{result.rowcount} rows",
                    flush=True,
                )
                total += result.rowcount

    engine.dispose()
    print(f"backfill_salary_currency: done, {total} rows updated", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"backfill_salary_currency: FAILED — {e}", file=sys.stderr, flush=True)
        sys.exit(0)  # don't fail boot
