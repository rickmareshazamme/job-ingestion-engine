"""GeoNames cities500 lookup — resolve (country_iso, city_name) to lat/lng.

Loads ~232K cities (population >= 500) from GeoNames public-domain dump.
Cached on disk at /tmp/cities500.json after first download. Loaded into
memory once per worker process; ~25 MB RAM, instant lookups thereafter.

Data source: https://download.geonames.org/export/dump/cities500.zip
License: CC-BY-4.0 (GeoNames).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import urllib.request
import zipfile
from threading import Lock
from typing import Optional

logger = logging.getLogger("zammejobs.geo.cities")

GEONAMES_URL = "https://download.geonames.org/export/dump/cities500.zip"
CACHE_PATH = "/tmp/cities500.json"

# Indexed by (country_iso_upper, normalized_city_name) → (lat, lng, population)
_INDEX: dict[tuple[str, str], tuple[float, float, int]] = {}
_INDEX_LOADED = False
_LOCK = Lock()


def _normalize(s: str) -> str:
    """Lowercase + strip diacritics-light + drop non-alpha so 'St. Louis' matches 'st louis'."""
    if not s:
        return ""
    s = s.lower().strip()
    # Common substitutions
    s = s.replace("st.", "st").replace("ste.", "ste").replace("mt.", "mt")
    # Drop punctuation + extra whitespace
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _ensure_data() -> str:
    """Download cities500.zip to CACHE_PATH if not already there. Return path."""
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 1_000_000:
        return CACHE_PATH

    logger.info("Downloading GeoNames cities500 to %s", CACHE_PATH)
    with urllib.request.urlopen(GEONAMES_URL, timeout=120) as r:
        zf_bytes = r.read()
    zf = zipfile.ZipFile(io.BytesIO(zf_bytes))
    with zf.open("cities500.txt") as f:
        text = f.read().decode("utf-8")

    rows = []
    for line in text.split("\n"):
        p = line.split("\t")
        if len(p) < 15:
            continue
        try:
            rows.append({
                "n": p[1],
                "a": p[2],
                "lat": float(p[4]),
                "lng": float(p[5]),
                "cc": p[8],
                "pop": int(p[14]) if p[14].isdigit() else 0,
            })
        except (ValueError, IndexError):
            continue

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    logger.info("Cached %d cities to %s (%d MiB)", len(rows), CACHE_PATH, os.path.getsize(CACHE_PATH) // (1 << 20))
    return CACHE_PATH


def _load() -> None:
    """One-time: build the in-memory (country, city) → coords index."""
    global _INDEX_LOADED
    if _INDEX_LOADED:
        return
    with _LOCK:
        if _INDEX_LOADED:
            return
        path = _ensure_data()
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        for r in rows:
            cc = (r["cc"] or "").upper()
            if not cc:
                continue
            # Index by both the localized and ASCII names so "Köln" and "Cologne" both resolve
            for nm in (r["n"], r["a"]):
                key = (cc, _normalize(nm))
                if key in _INDEX:
                    # Keep the larger-population entry on collision
                    if r["pop"] > _INDEX[key][2]:
                        _INDEX[key] = (r["lat"], r["lng"], r["pop"])
                else:
                    _INDEX[key] = (r["lat"], r["lng"], r["pop"])
        _INDEX_LOADED = True
        logger.info("Cities index loaded: %d (city, country) entries", len(_INDEX))


def lookup(country_iso: Optional[str], city_name: Optional[str]) -> Optional[tuple[float, float]]:
    """Resolve (country, city) → (lat, lng). Returns None if not found.

    Tries exact match, then the first comma-segment of city_name (handles
    "Berlin, Germany" → "Berlin").
    """
    if not city_name or not country_iso:
        return None
    _load()
    cc = country_iso.upper()
    if cc == "UK":
        cc = "GB"
    name = _normalize(city_name)
    if not name:
        return None
    hit = _INDEX.get((cc, name))
    if hit:
        return (hit[0], hit[1])
    # Try first comma-segment ("Sydney, Australia" → "Sydney")
    if "," in city_name:
        first = _normalize(city_name.split(",", 1)[0])
        hit = _INDEX.get((cc, first))
        if hit:
            return (hit[0], hit[1])
    # Try first hyphen-segment ("New-York" → "new york" already done; try "los-angeles-ca")
    if "-" in name:
        first = name.split("-", 1)[0].strip()
        if first and len(first) >= 3:
            hit = _INDEX.get((cc, first))
            if hit:
                return (hit[0], hit[1])
    return None


def lookup_country_centroid(country_iso: Optional[str]) -> Optional[tuple[float, float]]:
    """Pick the largest city in a country as a country-level marker."""
    if not country_iso:
        return None
    _load()
    cc = country_iso.upper()
    if cc == "UK":
        cc = "GB"
    best: Optional[tuple[float, float, int]] = None
    for (k_cc, _name), (lat, lng, pop) in _INDEX.items():
        if k_cc != cc:
            continue
        if best is None or pop > best[2]:
            best = (lat, lng, pop)
    return (best[0], best[1]) if best else None
