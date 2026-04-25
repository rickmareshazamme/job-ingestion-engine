"""Discover career sites from Common Crawl data.

Queries the Common Crawl index for known ATS URL patterns to find
companies using each ATS platform — without crawling any sites ourselves.

Usage:
    python3 -m scripts.discover_from_commoncrawl
    python3 -m scripts.discover_from_commoncrawl --ats greenhouse
"""

import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover.commoncrawl")


async def main():
    from src.discovery.common_crawl import discover_career_sites_from_cc

    ats_filter = None
    if "--ats" in sys.argv:
        idx = sys.argv.index("--ats")
        if idx + 1 < len(sys.argv):
            ats_filter = sys.argv[idx + 1]

    logger.info("Discovering career sites from Common Crawl index...")
    all_discoveries = await discover_career_sites_from_cc(max_per_ats=500)

    total_tokens = 0
    for ats, tokens in sorted(all_discoveries.items(), key=lambda x: -len(x[1])):
        if ats_filter and ats != ats_filter:
            continue
        logger.info("\n%s: %d board tokens found", ats.upper(), len(tokens))
        for token in tokens[:20]:
            logger.info("  %s", token)
        if len(tokens) > 20:
            logger.info("  ... and %d more", len(tokens) - 20)
        total_tokens += len(tokens)

    logger.info("\n=== TOTAL: %d unique board tokens across %d ATS platforms ===", total_tokens, len(all_discoveries))

    with open("commoncrawl_discoveries.json", "w") as f:
        json.dump(all_discoveries, f, indent=2)
    logger.info("Saved to commoncrawl_discoveries.json")


if __name__ == "__main__":
    asyncio.run(main())
