"""
Scrape the 2016 national and local election results from GMA's Eleksyon 2016 feed into
data/raw_data/2016/, in the same per-municipality CSV schema as every other cycle.

    python data/scraping/scrape_2016_gma.py
    python data/scraping/scrape_2016_gma.py --province PALAWAN

No browser required: GMA's results are static gzipped JSON on a CDN, so this is plain
HTTP and runs concurrently.

Why GMA and not ABS-CBN for 2016
--------------------------------
ABS-CBN's 2016 site (2016halalanresults.abs-cbn.com) is a DEAD ARCHIVE. It is now static
files on S3 and every vote endpoint - ajax/loc-local.php, loc-national.php, hor-local.php -
returns 404. Its cache-json.json holds 44,872 candidates but no votes at all. It cannot be
used as a results source.

It is still useful for one thing: cache-location.html is a complete 2016 locality index,
which GMA never publishes. So the locality list comes from ABS-CBN and the votes from GMA.

The feed
--------
  {GMA}/all_lvgs_results/{REGION}_{PROVINCE}_{CITY}.json.gz
        every contest in one municipality, with vote counts

The filename is GMA's `location_code` ("REGION I|ILOCOS NORTE|ADAMS") with every character
outside [A-Za-z0-9_-] replaced by an underscore. GMA does this LITERALLY, so a name with a
double space becomes a double underscore and a parenthetical keeps its brackets as
underscores. The locality index we build the name from does not always agree with GMA on
that whitespace, so each locality is tried under a few spellings (see NAME_VARIANTS).

GMA's hierarchy is COMELEC's own, which means two wrinkles:
  * Independent cities (Cebu City, Davao City, Baguio City...) are promoted to the PROVINCE
    level - "REGION VII|CEBU CITY|CEBU CITY", not under Cebu province.
  * Metro Manila is split into NCR legislative districts, exactly as COMELEC 2022/2025 does.

Contest strings are the same COMELEC vocabulary as the 2022 scrape ("MAYOR ILOCOS NORTE -
ADAMS", "MEMBER, SANGGUNIANG PANLALAWIGAN ... - FIRST PROVDIST"), so the existing office
parser handles them unchanged.
"""

import argparse
import csv
import gzip
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

from config import raw_dir

GMA = "https://eleksyondata3.gmanews.tv/all_lvgs_results"
GMA_REGIONS = ("https://data.gmanews.tv/gno/microsites/eleksyon2016/results"
               "/mapping/highmaps_mapped_comelec.json")
ABSCBN_LOCATIONS = "https://2016halalanresults.abs-cbn.com/cache-location.html"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

FIELDS = ["region", "province", "city", "position", "rank",
          "candidate_name", "party", "votes", "percentage"]

# Metro Manila's LGUs and the NCR district GMA files them under.
NCR = {
    "CITY OF MANILA": "NATIONAL CAPITAL REGION - MANILA",
    "CITY OF MANDALUYONG": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "CITY OF MARIKINA": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "CITY OF PASIG": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "CITY OF SAN JUAN": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "QUEZON CITY": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "CALOOCAN CITY": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "CITY OF MALABON": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "CITY OF NAVOTAS": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "CITY OF VALENZUELA": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "CITY OF LAS PIÑAS": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF MAKATI": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF MUNTINLUPA": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF PARAÑAQUE": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "PASAY CITY": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF TAGUIG": "TAGUIG - PATEROS",
    "PATEROS": "TAGUIG - PATEROS",
}


def slug(text):
    """
    Reproduce GMA's own getFileName() exactly.

    Per character: keep it if it matches JavaScript's [\w-] (ASCII letters, digits,
    underscore, hyphen); otherwise emit an underscore - and emit a SECOND underscore for
    n-tilde, which its code special-cases. So "SOFRONIO ESPANOLA" with a tilde becomes
    SOFRONIO_ESPA__OLA, and "BROOKE'S POINT" becomes BROOKE_S_POINT.

    Note this must be an ASCII test: Python's \w would happily match the n-tilde and
    silently diverge from GMA.
    """
    out = []
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch)
        else:
            out.append("_")
            if ch in "\u00f1\u00d1":  # n-tilde: GMA emits two underscores
                out.append("_")
    return "".join(out).upper()


def name_variants(region, province, city):
    """
    Candidate filenames for one locality.

    The locality index and GMA disagree on incidental whitespace ("TANJAY  CITY") and on
    parentheticals ("PICONG  (SULTAN GUMANDER)"), so try the obvious spellings rather than
    guessing which one GMA used.
    """
    seen, out = set(), []
    cities = [
        city,
        re.sub(r"\s+", " ", city).strip(),           # collapse runs of spaces
        re.sub(r"\s*\(.*?\)\s*", "", city).strip(),   # drop a parenthetical
        city.replace("'", ""),                       # BROOKE'S POINT vs BROOKES POINT
        re.sub(r"([A-Z])S ", r"\1'S ", city, count=1),  # ...and the reverse
    ]
    for c in cities:
        base = slug(f"{region}_{province}_{c}")
        for candidate in (base, re.sub(r"_+", "_", base)):  # collapse runs of underscores
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    return out


class Feed:
    def __init__(self):
        self._local = threading.local()

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
        return self._local.session

    def results(self, filename):
        """
        Fetch one locality's results, or None if GMA has no such file.

        The file is .json.gz AND is served with Content-Encoding: gzip, so requests may
        already have decompressed it. Try raw first, then gunzip.
        """
        try:
            r = self.session.get(f"{GMA}/{filename}.json.gz", timeout=30)
            if r.status_code != 200:
                return None
            try:
                return json.loads(r.content)
            except (ValueError, UnicodeDecodeError):
                return json.loads(gzip.decompress(r.content))
        except Exception:
            return None


# Provinces GMA's map omits entirely. Both are recent provinces; their results exist, but
# the map never lists them, so their region has to be supplied.
MISSING_FROM_GMA_MAP = {
    "DINAGAT ISLANDS": "REGION XIII",
    "DAVAO OCCIDENTAL": "REGION XI",
}


def _fold(name):
    """
    Fold a PROVINCE name for matching across the two references.

    Keep the parenthetical: it disambiguates. Dropping it makes "COTABATO (NORTH COT.)"
    collide with "COTABATO CITY", which silently files every Cotabato municipality under
    Cotabato City in ARMM instead of Cotabato province in Region XII.
    """
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _fold_city(name):
    """Fold a CITY name, so "CITY OF BUTUAN" matches GMA's "BUTUAN CITY"."""
    n = re.sub(r"^CITY OF\s+", "", name.upper())
    n = re.sub(r"\s+CITY$", "", n)
    return re.sub(r"[^A-Z0-9]", "", n)


def load_localities():
    """(region, gma_province, city, real_province) for every 2016 locality."""
    regions = requests.get(GMA_REGIONS, headers=HEADERS, timeout=30).json()
    province_region = {p["comelec_name"].upper(): p["region"].upper() for p in regions}

    folded = {_fold(name): name for name in province_region}
    # Independent cities only: GMA promotes them to the province level.
    independent = {_fold_city(name): name for name in province_region if "CITY" in name}

    index = requests.get(ABSCBN_LOCATIONS, headers=HEADERS, timeout=60).json()
    entries = index["location"] if isinstance(index, dict) else index

    out, unmapped = [], set()
    for entry in entries:
        for c in entry.get("city", []):
            province = c["locationname"].split(",")[-1].strip().upper()
            if province.startswith("WHOLE"):
                continue  # a province-level aggregate, not a locality
            city = c["city"].upper()

            if province == "METRO MANILA":
                bucket = NCR.get(city)
            elif province in province_region:
                bucket = province                       # exact match wins
            elif _fold(province) in folded:
                bucket = folded[_fold(province)]
            elif _fold_city(city) in independent:
                bucket = independent[_fold_city(city)]  # an independent city
            else:
                bucket = province
            if not bucket:
                continue

            region = province_region.get(bucket) or MISSING_FROM_GMA_MAP.get(_fold(province).replace("ISLANDS", " ISLANDS")) \
                or MISSING_FROM_GMA_MAP.get(province)
            if not region:
                unmapped.add(province)
                continue
            out.append((region, bucket, city, province))

    if unmapped:
        print(f"  WARNING: no region for {sorted(unmapped)} - those localities are skipped")
    return out


def to_rows(data, region, province, city):
    rows = []
    for contest in data.get("result", []):
        candidates = contest.get("candidates", [])
        total = sum(int(c.get("vote_count") or 0) for c in candidates)

        # GMA does not rank; sort by votes so `rank` means what it says.
        ordered = sorted(candidates, key=lambda c: int(c.get("vote_count") or 0),
                         reverse=True)
        for i, cand in enumerate(ordered, 1):
            votes = int(cand.get("vote_count") or 0)
            # party is "FULL NAME|ABBREV"; keep the abbreviation, like every other cycle
            party = (cand.get("party") or "").split("|")[-1].strip()
            rows.append({
                "region": region,
                "province": province,
                "city": city,
                "position": contest.get("contest", ""),
                "rank": i,
                "candidate_name": cand.get("name", ""),
                "party": party,
                "votes": votes,
                "percentage": f"{100 * votes / total:.2f} %" if total else "",
            })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Scrape GMA Eleksyon 2016 into data/raw_data/2016/")
    ap.add_argument("--province", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    only = {p.upper() for p in args.province}
    out_root = raw_dir(2016)
    feed = Feed()

    localities = load_localities()
    print(f"{len(localities):,} localities (GMA regions x ABS-CBN locality index)")
    if only:
        localities = [l for l in localities if l[3] in only or l[1] in only]
        print(f"--province filter: {len(localities)}")

    todo = []
    for region, bucket, city, province in localities:
        path = (out_root / slug(region) / slug(province) /
                f"{slug(region)}_{slug(province)}_{slug(city)}.csv")
        if path.exists() and not args.force:
            continue
        todo.append((region, bucket, city, province, path))

    print(f"{len(todo):,} to fetch\n")

    scraped = 0
    missing = []
    lock = threading.Lock()

    def work(item):
        region, bucket, city, province, path = item
        for filename in name_variants(region, bucket, city):
            data = feed.results(filename)
            if not data:
                continue
            rows = to_rows(data, region, province, city)
            if not rows:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
            return city, province, len(rows)
        return city, province, None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, i) for i in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            city, province, rows = fut.result()
            with lock:
                if rows is None:
                    missing.append(f"{city}, {province}")
                else:
                    scraped += 1
                if n % 100 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}  scraped={scraped} missing={len(missing)}",
                          flush=True)

    print(f"\nDone. scraped={scraped} missing={len(missing)}")
    if missing:
        # Never hide a gap: a locality GMA has no file for must show up in the audit.
        print(f"\n{len(missing)} localities GMA has no results for:")
        for m in sorted(missing):
            print(f"  - {m}")


if __name__ == "__main__":
    main()
