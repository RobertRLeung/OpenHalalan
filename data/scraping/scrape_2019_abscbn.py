"""
Scrape the 2019 national and local election results from ABS-CBN's Halalan 2019 feed
into data/raw_data/2019/, in the same per-municipality CSV schema as the COMELEC scrapes.

    python data/scraping/scrape_2019_abscbn.py
    python data/scraping/scrape_2019_abscbn.py --province PALAWAN

No browser required. The site is an Angular front end over a STATIC JSON feed, so this is
plain HTTP: fast, resumable, and far more reliable than driving a real browser.

The feed
--------
  {FEED}/feed-0/ref-location-flat.json
        every location: 81 provinces + 1,693 municipalities, each with a locationCode

  {FEED}/feed-0/contest-location-municipality-{locationCode}.json
        for one municipality, the contestCode + locationCode of each office on its ballot

  {FEED}/feed-999/{office}-{contestCode}-{level}-location-{locationCode}.json
        the actual votes. feed-999 is the final (100% transmitted) feed.

Two quirks worth knowing:
  * Councilors resolve at the `municipal-district` level, not `municipality`, and carry a
    different locationCode than the municipality they sit in. Both come from the
    contest-location file - never assume the municipality's own code.
  * `rank` in this feed really is vote order (unlike COMELEC 2022, where it is an
    ALPHABETICAL index). We record it, but the winners builder sorts by votes regardless.

Output: data/raw_data/2019/{REGION}/{PROVINCE}/{REGION}_{PROVINCE}_{CITY}.csv with the
columns region, province, city, position, rank, candidate_name, party, votes, percentage -
identical to the COMELEC scrapes, so the existing compile step handles it unchanged.
"""

import argparse
import csv
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

from config import raw_dir

FEED = "https://halalan-result-files-2019.abs-cbn.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# The feed's position keys -> the URL slug, and the location level the office resolves at.
# Councilors are the odd one out: they sit at municipal-district level.
POSITIONS = {
    "SENATOR": ("senator", "municipality"),
    "PARTY_LIST": ("party-list", "municipality"),
    "GOVERNOR": ("governor", "municipality"),
    "VICE_GOVERNOR": ("vice-governor", "municipality"),
    "CONGRESSMAN": ("congressman", "municipality"),
    "PROVINCIAL_BOARD_MEMBER": ("provincial-board-member", "municipality"),
    "MAYOR": ("mayor", "municipality"),
    "VICE_MAYOR": ("vice-mayor", "municipality"),
    "COUNCILOR": ("councilor", "municipal-district"),
}

FIELDS = ["region", "province", "city", "position", "rank",
          "candidate_name", "party", "votes", "percentage"]


def safe(name):
    """Filesystem-safe upper-case token, matching the COMELEC scrapes' convention."""
    return str(name).upper().replace(" ", "_").replace("/", "_").replace(",", "")


class Feed:
    """Thread-safe HTTP client. Each worker thread keeps its own connection pool."""

    def __init__(self):
        self._local = threading.local()

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
        return self._local.session

    def get(self, path, retries=3):
        url = f"{FEED}/{path}"
        for attempt in range(retries):
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except Exception:
                if attempt == retries - 1:
                    return None
                time.sleep(1.5 * (attempt + 1))
        return None


def load_locations(feed):
    """Return (municipalities, province -> region)."""
    flat = feed.get("feed-0/ref-location-flat.json")
    if not flat:
        sys.exit("could not load ref-location-flat.json")

    # A province's fullLocationName is "<PROVINCE>, <REGION>" - the only place the region
    # is recorded, so the municipalities inherit it via their province.
    province_region = {}
    for loc in flat:
        if loc["locationType"] == "province":
            name = loc["locationName"]
            full = loc["fullLocationName"]
            province_region[name] = full.split(",")[-1].strip() if "," in full else ""

    # Metro Manila is NOT a province in this feed, so its 17 LGUs would otherwise come
    # through with an empty region. Give them one.
    province_region["METRO MANILA"] = "NATIONAL CAPITAL REGION"

    # The feed's 1,693 "municipalities" also include 59 OVERSEAS POSTS (embassies and
    # consulates, e.g. "VIENNA PE, EUROPE"), grouped under an overseas region rather than
    # a province. They carry no local races and return no results here. Dropping them
    # leaves exactly the 1,634 Philippine cities and municipalities - the same count as
    # the 2022 COMELEC scrape.
    #
    # Overseas absentee votes are therefore NOT in this dataset, the same way LAV (local
    # absentee voting) is set aside for 2025.
    municipalities = [
        loc for loc in flat
        if loc["locationType"] == "municipality"
        and loc["fullLocationName"].split(",")[-1].strip() in province_region
    ]
    overseas = sum(1 for loc in flat if loc["locationType"] == "municipality") - len(municipalities)
    if overseas:
        print(f"  excluding {overseas} overseas posts (no local races)")

    return municipalities, province_region


def scrape_municipality(feed, muni, province_region):
    """Fetch every contest on one municipality's ballot. Returns a list of CSV rows."""
    # "ABORLAN, PALAWAN" -> province is whatever follows the comma.
    full = muni["fullLocationName"]
    city = muni["locationName"]
    province = full.split(",")[-1].strip() if "," in full else ""
    region = province_region.get(province, "")

    contests = feed.get(f"feed-0/contest-location-municipality-{muni['locationCode']}.json")
    if not contests:
        return []

    rows = []
    for key, entry in contests.items():
        if key not in POSITIONS:
            continue
        slug, level = POSITIONS[key]

        for pair in entry.get("contestCodeAndLocationCode", []):
            # Take BOTH codes from the feed. The councilor contest carries a different
            # locationCode than the municipality it belongs to.
            path = (f"feed-999/{slug}-{pair['contestCode']}-{level}"
                    f"-location-{pair['locationCode']}.json")
            data = feed.get(path)
            if not data or not data.get("result"):
                continue

            results = data["result"]

            # voteCount is usually an int but the feed sometimes ships it as a string.
            def vote_count(cand):
                try:
                    return int(cand.get("voteCount") or 0)
                except (TypeError, ValueError):
                    return 0

            total = sum(vote_count(c) for c in results)

            for cand in results:
                votes = vote_count(cand)
                rows.append({
                    "region": region,
                    "province": province,
                    "city": city,
                    # contestDetail is already in the same shape as the 2022 COMELEC
                    # position strings ("MAYOR PALAWAN - ABORLAN"), so the existing
                    # office parser handles it with no special case.
                    "position": data.get("contestDetail") or data.get("positionName", ""),
                    "rank": cand.get("rank", ""),
                    "candidate_name": cand.get("candidateName", ""),
                    "party": cand.get("partyNameShort") or cand.get("partyName") or "",
                    "votes": votes,
                    "percentage": f"{100 * votes / total:.2f} %" if total else "",
                })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Scrape ABS-CBN Halalan 2019 into data/raw_data/2019/")
    ap.add_argument("--province", action="append", default=[],
                    help="only scrape this province (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch municipalities already on disk")
    ap.add_argument("--workers", type=int, default=12,
                    help="concurrent municipalities (default 12)")
    args = ap.parse_args()

    only = {p.upper() for p in args.province}
    out_root = raw_dir(2019)
    feed = Feed()

    municipalities, province_region = load_locations(feed)
    print(f"feed lists {len(municipalities):,} municipalities across "
          f"{len(province_region)} provinces")

    if only:
        municipalities = [
            m for m in municipalities
            if m["fullLocationName"].split(",")[-1].strip().upper() in only
        ]
        print(f"--province filter: {len(municipalities)} municipalities")

    # Each municipality needs ~10 sequential fetches, so this is latency-bound, not
    # bandwidth-bound: run municipalities concurrently. The feed is static files on a CDN.
    todo = []
    for muni in municipalities:
        full = muni["fullLocationName"]
        province = full.split(",")[-1].strip() if "," in full else ""
        region = province_region.get(province, "")
        path = (out_root / safe(region) / safe(province) /
                f"{safe(region)}_{safe(province)}_{safe(muni['locationName'])}.csv")
        todo.append((muni, path))

    skipped = sum(1 for _, p in todo if p.exists() and not args.force)
    todo = [(m, p) for m, p in todo if args.force or not p.exists()]
    print(f"{len(todo):,} to fetch, {skipped:,} already on disk\n")

    scraped = failed = 0
    empty = []
    done = 0
    lock = threading.Lock()

    def work(item):
        muni, path = item
        rows = scrape_municipality(feed, muni, province_region)
        if not rows:
            return muni, path, None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return muni, path, len(rows)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, item) for item in todo]
        for fut in as_completed(futures):
            muni, path, n = fut.result()
            with lock:
                done += 1
                if n is None:
                    failed += 1
                    empty.append(muni["fullLocationName"])
                else:
                    scraped += 1
                if done % 50 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}  scraped={scraped} failed={failed}",
                          flush=True)

    print(f"\nDone. scraped={scraped} skipped={skipped} failed={failed}")
    if empty:
        # Report, never hide: a municipality the feed lists but returns nothing for is a
        # real gap and must show up in the audit rather than vanish silently.
        print(f"\n{len(empty)} municipalities returned NO RESULTS:")
        for name in sorted(empty):
            print(f"  - {name}")
    print(f"Output: {out_root}")


if __name__ == "__main__":
    main()
