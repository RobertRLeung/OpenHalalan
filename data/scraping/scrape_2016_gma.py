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

NCR_UMBRELLA = {"METRO MANILA", "NCR", "NATIONAL CAPITAL REGION"}

# Metro Manila's LGUs and the NCR district GMA files them under. Keys cover both the
# 2019 roster's spellings ("QUEZON CITY") and the "CITY OF X" form.
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
    "TAGUIG": "TAGUIG - PATEROS",
    "PATEROS": "TAGUIG - PATEROS",
    "MANILA": "NATIONAL CAPITAL REGION - MANILA",
    "MANDALUYONG": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "MARIKINA": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "PASIG": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "SAN JUAN": "NATIONAL CAPITAL REGION - SECOND DISTRICT",
    "CALOOCAN": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "MALABON": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "NAVOTAS": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "VALENZUELA": "NATIONAL CAPITAL REGION - THIRD DISTRICT",
    "LAS PINAS": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF LAS PINAS": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "MAKATI": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "MUNTINLUPA": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "PARANAQUE": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "CITY OF PARANAQUE": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
    "PASAY": "NATIONAL CAPITAL REGION - FOURTH DISTRICT",
}


# NCR districts that contain exactly one city, so GMA files them with no city component.
DISTRICT_IS_THE_CITY = {"NATIONAL CAPITAL REGION - MANILA"}


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

    # A district that IS a single city carries no city component at all: Manila's file is
    # NCR_NATIONAL_CAPITAL_REGION_-_MANILA, with nothing after it.
    if province in DISTRICT_IS_THE_CITY:
        out.append(slug(f"{region}_{province}"))

    bases = {city}
    bases.add(re.sub(r"\s+", " ", city).strip())            # collapse runs of spaces
    bases.add(re.sub(r"\s*\(.*?\)\s*", "", city).strip())    # drop a parenthetical
    # ...and try the parenthetical ITSELF: the roster carries the current name with the
    # old one in brackets ("AMAI MANABILANG (BUMBARAN)"), but in 2016 the place was still
    # BUMBARAN, which is the only name GMA knows it by.
    alt = re.search(r"\((.*?)\)", city)
    if alt:
        bases.add(alt.group(1).strip())
    bases.add(city.replace("'", ""))                        # BROOKE'S POINT / BROOKES POINT
    # GMA writes the bare name where the locality index writes "CITY OF TAGUIG".
    for c in list(bases):
        bases.add(re.sub(r"^CITY OF\s+", "", c).strip())
        bases.add(re.sub(r"\s+CITY$", "", c).strip())

    for c in bases:
        if not c:
            continue
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


# NCR keyed by folded city name, so "MALABON CITY", "CITY OF MALABON" and "MALABON"
# all resolve to the same district.
NCR_FOLDED = None


def _ncr_district(city):
    """NCR district for a city, tolerant of CITY OF X / X CITY / X spellings."""
    global NCR_FOLDED
    if NCR_FOLDED is None:
        NCR_FOLDED = {_fold_city(k): v for k, v in NCR.items()}
    return NCR.get(city) or NCR_FOLDED.get(_fold_city(city))


def load_localities():
    """
    (region, gma_province, city, real_province) for every 2016 locality.

    The locality list comes from our OWN 2019 scrape, not from ABS-CBN's 2016 index.

    ABS-CBN files independent cities under a province of their own name ("BUTUAN CITY"
    rather than Agusan del Norte), which has no region in GMA's map, so 31 of the
    country's largest cities - Cebu, Davao, Baguio, Iloilo, Bacolod, Zamboanga - were
    being silently dropped before they were ever requested. The 2019 scrape is the
    authoritative 1,634-locality roster and puts every city under its real province.

    Only the REGION is taken from GMA (its 2016 map still says ARMM, not BARMM).
    """
    regions = requests.get(GMA_REGIONS, headers=HEADERS, timeout=30).json()
    province_region = {p["comelec_name"].upper(): p["region"].upper() for p in regions}
    folded = {_fold(name): name for name in province_region}

    roster = raw_dir(2019)
    if not roster.exists():
        sys.exit(f"need the 2019 scrape as the locality roster: {roster} is missing")

    out, unmapped = [], set()
    seen = set()
    for f in sorted(roster.rglob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            row = next(csv.DictReader(fh), None)
        if not row:
            continue

        province = (row["province"] or "").strip().upper()
        city = (row["city"] or "").strip().upper()
        if (province, city) in seen:
            continue
        seen.add((province, city))

        if province in NCR_UMBRELLA:
            # The roster spells these "MALABON CITY" / "CITY OF MALABON" / "MALABON".
            bucket = _ncr_district(city)
        elif province in province_region:
            bucket = province
        elif _fold(province) in folded:
            bucket = folded[_fold(province)]
        elif province in MISSING_FROM_GMA_MAP:
            bucket = province      # a province GMA's map omits; region supplied below
        else:
            bucket = None

        if not bucket:
            unmapped.add(f"{city}, {province}")
            continue

        region = province_region.get(bucket) or MISSING_FROM_GMA_MAP.get(province)
        if not region:
            unmapped.add(f"{city}, {province}")
            continue

        out.append((region, bucket, city, province))

    if unmapped:
        print(f"  WARNING: {len(unmapped)} localities could not be mapped to a GMA region:")
        for u in sorted(unmapped):
            print(f"    {u}")
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
