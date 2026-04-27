"""One-shot Common Crawl JobPosting harvester.

Fires the same code path as the Celery beat task, but synchronously, so it
can be triggered ad-hoc on Railway:

    railway ssh -s web -- "python3 -m scripts.harvest_common_crawl --max-files 1"

Flags:
    --crawl-id     WDC crawl id, e.g. "2024-12" (default)
    --max-files    Number of NQ files to pull from that crawl (default 1)
    --max-records  Stop after N RawJobs across all files (default 50_000)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.tasks.crawl import harvest_common_crawl


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--crawl-id", default="2024-12")
    p.add_argument("--max-files", type=int, default=1)
    p.add_argument("--max-records", type=int, default=50_000)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    # Invoke the Celery task body directly, bypassing the broker.
    # Celery exposes the wrapped function via .run; using .apply()
    # gives us the same execution surface (incl. self.retry) without
    # requiring Redis to be reachable.
    result = harvest_common_crawl.apply(
        kwargs={
            "crawl_id": args.crawl_id,
            "max_files": args.max_files,
            "max_records": args.max_records,
        }
    )

    if result.failed():
        print(f"FAILED: {result.traceback}", file=sys.stderr)
        return 1

    print(json.dumps(result.result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
