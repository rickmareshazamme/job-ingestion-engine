"""Discover career sites from a list of company domains.

Given any company domain, probes for career pages, detects ATS platform,
and extracts board tokens for automatic job ingestion.

Usage:
    # Probe a single domain
    python3 -m scripts.discover_from_domains stripe.com

    # Probe from a file (one domain per line)
    python3 -m scripts.discover_from_domains --file domains.txt

    # Probe Fortune 500 domains
    python3 -m scripts.discover_from_domains --fortune500
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover.domains")

# Sample Fortune 500 / major company domains
FORTUNE_500_DOMAINS = [
    "apple.com", "microsoft.com", "amazon.com", "google.com", "meta.com",
    "berkshirehathaway.com", "unitedhealth.com", "jpmorgan.com", "exxonmobil.com",
    "walmart.com", "chevron.com", "jnj.com", "pfizer.com", "procter.com",
    "visa.com", "mastercard.com", "nike.com", "disney.com", "netflix.com",
    "salesforce.com", "adobe.com", "cisco.com", "oracle.com", "ibm.com",
    "intel.com", "nvidia.com", "paypal.com", "uber.com", "airbnb.com",
    "stripe.com", "shopify.com", "twilio.com", "datadog.com", "cloudflare.com",
    "snowflake.com", "mongodb.com", "hashicorp.com", "okta.com", "zscaler.com",
    "crowdstrike.com", "paloaltonetworks.com", "fortinet.com",
    "deloitte.com", "pwc.com", "ey.com", "kpmg.com", "accenture.com",
    "mckinsey.com", "bcg.com", "bain.com",
    "goldmansachs.com", "morganstanley.com", "bankofamerica.com", "wellsfargo.com",
    "citigroup.com", "americanexpress.com", "blackrock.com",
    "boeing.com", "lockheedmartin.com", "raytheon.com", "northropgrumman.com",
    "generalmotors.com", "ford.com", "tesla.com", "rivian.com",
    "cocacola.com", "pepsico.com", "starbucks.com", "mcdonalds.com",
    "homedepot.com", "lowes.com", "costco.com", "target.com",
    "unitedairlines.com", "delta.com", "southwest.com",
    "att.com", "verizon.com", "tmobile.com", "comcast.com",
    "anthem.com", "cigna.com", "humana.com", "cvs.com",
    "merck.com", "abbvie.com", "amgen.com", "gilead.com",
    "medtronic.com", "abbott.com", "baxter.com",
    "caterpillar.com", "deere.com", "honeywell.com", "3m.com",
    "dukeenergy.com", "nexteraenergy.com", "southerncompany.com",
    "ups.com", "fedex.com",
    # Tech / Startups
    "figma.com", "notion.so", "discord.com", "reddit.com", "snapchat.com",
    "pinterest.com", "spotify.com", "canva.com", "atlassian.com",
    "databricks.com", "github.com", "gitlab.com", "vercel.com",
    "supabase.com", "linear.app", "openai.com", "anthropic.com",
    "duolingo.com", "coursera.org", "doordash.com", "instacart.com",
    "robinhood.com", "coinbase.com", "plaid.com", "brex.com",
]


async def main():
    from src.discovery.career_page_finder import discover_career_sites, save_discoveries

    domains = []

    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        # Single domain
        domains = [sys.argv[1]]
    elif "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 < len(sys.argv):
            path = Path(sys.argv[idx + 1])
            if path.exists():
                with open(path) as f:
                    domains = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                logger.info("Loaded %d domains from %s", len(domains), path)
    elif "--fortune500" in sys.argv:
        domains = FORTUNE_500_DOMAINS
    else:
        domains = FORTUNE_500_DOMAINS[:20]  # Default: first 20

    logger.info("Probing %d domains for career pages...", len(domains))
    discoveries = await discover_career_sites(domains, concurrency=5)

    logger.info("\n=== RESULTS ===")
    logger.info("Found career sites: %d / %d domains", len(discoveries), len(domains))

    by_ats = {}
    for d in discoveries:
        ats = d.ats_platform or "unknown"
        by_ats.setdefault(ats, []).append(d)

    for ats, sites in sorted(by_ats.items(), key=lambda x: -len(x[1])):
        logger.info("\n%s (%d):", ats.upper(), len(sites))
        for site in sites:
            logger.info("  %s → %s (token: %s)", site.domain, site.career_url, site.board_token)

    save_discoveries(discoveries)


if __name__ == "__main__":
    asyncio.run(main())
