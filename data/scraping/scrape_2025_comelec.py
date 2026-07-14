"""
Scrape the 2025 COMELEC results into data/raw_data/2025/ from COMELEC's JSON API.

    python data/scraping/scrape_2025_comelec.py
    python data/scraping/scrape_2025_comelec.py --province CAPIZ --force
    python data/scraping/scrape_2025_comelec.py --verify-only

Why this replaces the Selenium scraper
--------------------------------------
The old scraper drove a browser and read the RENDERED results table, so it captured only
the rows the page had bothered to render. That is the same design that silently truncated
2022 - the presidential race shipped with 7 of its 10 candidates in every municipality in
the country - and it did not survive contact with 2025 either:

    Dumalag, Capiz             16 of 155 party-list options, and NO local races at all
    Mabuhay, Zamboanga Sibugay 14 of 155 party-list options, and NO local races at all

Those two towns had no mayor, no vice mayor and no councilors in the published dataset.
COMELEC's servers held all of it the whole time; the scraper simply never saw it.

Reading a rendered table is guessing at what the data is. The API returns every ballot
option that exists, so truncation stops being a bug that can recur and becomes a bug that
cannot be expressed.

Cloudflare, and why every fetch runs inside the browser
-------------------------------------------------------
Unlike 2022's site, the 2025 site sits behind a Cloudflare challenge: plain HTTP gets a 403.
The obvious shortcut - clear the challenge in a browser, take the `cf_clearance` cookie, and
then fetch fast with `requests` - DOES NOT WORK, and fails in a way that looks like it
works: the cookie is bound to the client's TLS fingerprint (JA3), not merely to the cookie
and the user-agent, and `requests` cannot reproduce Chrome's handshake. A fresh token may
survive one or two calls and then start 403-ing mid-run.

So the browser stays open and every fetch is issued from inside the page, which is the one
client Cloudflare is certain about. Concurrency is not lost: each call hands the page a
batch of URLs and Promise.all fetches them together.

The API
-------
  data/regions/local/{code}.json   the location tree. categoryCode 2 = region, 3 = province,
                                   4 = city/municipality. "0" is the root.
  data/coc/{code}.json             a locality's certificate of canvass: every contest on its
                                   ballot and every candidate in each, with votes.

Output: data/raw_data/2025/{REGION}/{PROVINCE}/{REGION}_{PROVINCE}_{CITY}.csv, the same
schema as every other cycle, so the compile step handles it unchanged.

Completeness is checked, not assumed
------------------------------------
After the run it re-reads what was written and asserts what MUST be true: a national race
is the same ballot in every town in the country, so its candidate count has to be identical
everywhere, and a town that elects a mayor has one. Anything short is truncation by
definition. Failures are re-fetched, and if they are still short the script exits non-zero
and says so - because at that point the gap is COMELEC's, and a gap you report is a
different thing from a gap you never noticed. The old scraper had no such check. That is
why two towns sat in the published dataset with no local government in them.
"""

import argparse
import collections
import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import raw_dir

BASE = "https://2025electionresults.comelec.gov.ph"
ROOT_CODE = "0"

REGION, PROVINCE, CITY = "2", "3", "4"      # categoryCode in the region tree

FIELDS = ["region", "province", "city", "position", "rank",
          "candidate_name", "party", "votes", "percentage"]

# COMELEC writes a ballot option as "12. CASTRO, JANE (LAKAS)": ballot number, name, party.
# All three are wanted separately, and the number is not the rank - see below.
_OPTION = re.compile(r"^\s*\d+\.\s*(.*?)\s*(?:\(([^)]*)\))?\s*$")


def safe(name):
    """Filesystem-safe upper-case token, matching the other scrapes' convention."""
    return str(name).upper().replace(" ", "_").replace("/", "_").replace(",", "")


# Fetches a batch of URLs from inside the page and hands back the parsed JSON. A failure is
# null rather than an exception, so one bad path cannot lose the other 24 in its batch.
_FETCH_BATCH = """
const paths = arguments[0], done = arguments[arguments.length - 1];
Promise.all(paths.map(p =>
  fetch(p, {headers: {'Accept': 'application/json'}})
    .then(r => r.ok ? r.json() : null)
    .catch(() => null)
)).then(done);
"""


class Api:
    """Every request goes through the open browser, because Cloudflare will not accept any
    other client. Batched, so this is not as slow as it sounds."""

    BATCH = 25

    def __init__(self, driver):
        self.d = driver

    def get_many(self, paths, retries=3):
        """Parsed JSON for each path, in order. None where it could not be fetched."""
        out = [None] * len(paths)
        pending = list(range(len(paths)))

        for attempt in range(retries):
            if not pending:
                break
            still = []
            for i in range(0, len(pending), self.BATCH):
                chunk = pending[i:i + self.BATCH]
                got = self.d.execute_async_script(
                    _FETCH_BATCH, [f"/{paths[j]}" for j in chunk])
                for j, value in zip(chunk, got):
                    if value is None:
                        still.append(j)
                    else:
                        out[j] = value
            pending = still
            if pending:
                time.sleep(2 * (attempt + 1))   # a 403 here is throttling, so back off

        return out

    def get(self, path):
        return self.get_many([path])[0]


def open_browser():
    """A real browser, kept open for the whole run. Not headless: the challenge fails one."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    print("opening a browser and clearing Cloudflare ...")
    opts = Options()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=opts)
    driver.set_script_timeout(180)
    driver.get(f"{BASE}/")
    for _ in range(40):
        time.sleep(1)
        if any(c["name"] == "cf_clearance" for c in driver.get_cookies()):
            print("  cleared")
            return driver
    driver.quit()
    sys.exit("Cloudflare did not clear - try again")


def walk_cities(api):
    """Every city/municipality in the tree, with its region and province.

    Breadth-first, one batched round trip per level, rather than one request per node:
    the tree is three levels deep and a node-at-a-time walk is minutes of waiting."""
    cities = []
    frontier = [(ROOT_CODE, None, None)]      # (code, region, province)

    while frontier:
        nodes = api.get_many([f"data/regions/local/{code}.json" for code, _, _ in frontier])
        nxt = []
        for (_, region, province), node in zip(frontier, nodes):
            for child in (node or {}).get("regions", []):
                cat, name, code = child["categoryCode"], child["name"], child["code"]
                if cat == REGION:
                    nxt.append((code, name, None))
                elif cat == PROVINCE:
                    nxt.append((code, region, name))
                elif cat == CITY:
                    cities.append((region, province, name, code))
        frontier = nxt

    return cities


def coc_rows(region, province, city, coc):
    """Every contest on this locality's ballot, and every candidate in each."""
    if not coc:
        return []

    rows = []
    # "local" holds the locality's own races; "national" holds the senate and party-list
    # ballot it also canvasses. Both belong in the file, as in every other cycle.
    for contest in (coc.get("local") or []) + (coc.get("national") or []):
        options = ((contest.get("candidates") or {}).get("candidates")) or []

        tallied = []
        for opt in options:
            m = _OPTION.match(opt.get("name") or "")
            name = (m.group(1) if m else opt.get("name") or "").strip()
            party = (m.group(2) if m and m.group(2) else "").strip()
            tallied.append((name, party, int(opt.get("votes") or 0), opt.get("percentage")))

        # COMELEC lists options in BALLOT order and numbers them accordingly. `rank` in this
        # dataset means rank, so sort by votes - never trust the printed number.
        tallied.sort(key=lambda t: t[2], reverse=True)

        for i, (name, party, votes, pct) in enumerate(tallied, 1):
            rows.append({
                "region": region, "province": province, "city": city,
                "position": contest.get("contestName"),
                "rank": i,
                "candidate_name": name,
                "party": party,
                "votes": votes,
                "percentage": f"{pct} %" if pct is not None else "",
            })
    return rows


def fetch_all(api, out_root, cities, chunk=50):
    """Fetch and write a list of localities, a batch of COCs at a time."""
    written, empty = 0, []
    for i in range(0, len(cities), chunk):
        batch = cities[i:i + chunk]
        cocs = api.get_many([f"data/coc/{code}.json" for _, _, _, code in batch])
        for (region, province, city, _), coc in zip(batch, cocs):
            rows = coc_rows(region, province, city, coc)
            if rows:
                write(path_for(out_root, region, province, city), rows)
                written += 1
            else:
                empty.append(f"{city}, {province}")
        print(f"  {min(i + chunk, len(cities))}/{len(cities)}  "
              f"written={written} empty={len(empty)}", flush=True)

    if empty:
        print(f"\n  {len(empty)} returned no results:")
        for e in sorted(empty):
            print(f"     - {e}")
    return written, empty


def path_for(out_root, region, province, city):
    return (out_root / safe(region) / safe(province) /
            f"{safe(region)}_{safe(province)}_{safe(city)}.csv")


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- completeness

def verify(out_root, cities):
    """The check the old scraper never did.

    A national race is the SAME ballot in every town in the country, so its candidate count
    must be identical everywhere; anything short is truncation, by definition and without
    needing to know the right answer in advance. And a town that elects a mayor has one.
    Returns {(province, city): [reasons]} for the localities that fail."""
    per_race = collections.defaultdict(dict)
    has_mayor, on_disk = set(), []

    for region, province, city, code in cities:
        path = path_for(out_root, region, province, city)
        if not path.exists():
            continue
        on_disk.append((region, province, city, code))

        counts = collections.Counter()
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pos = (row["position"] or "").upper()
                counts[pos] += 1
                if pos.startswith("MAYOR"):
                    has_mayor.add((province, city))

        for race, n in counts.items():
            if race.startswith(("SENATOR", "PARTY LIST")):
                per_race[race][(province, city)] = n

    bad = {}
    for race, by_loc in per_race.items():
        if not by_loc:
            continue
        full = max(by_loc.values())          # the complete ballot, as observed
        for loc, n in by_loc.items():
            if n < full:
                bad.setdefault(loc, []).append(f"{race}: {n} of {full}")

    for _, province, city, _ in on_disk:
        if (province, city) not in has_mayor:
            bad.setdefault((province, city), []).append("no MAYOR race")

    return bad, on_disk


def main():
    ap = argparse.ArgumentParser(description="Scrape COMELEC 2025 into data/raw_data/2025/")
    ap.add_argument("--province", action="append", default=[])
    ap.add_argument("--force", action="store_true", help="re-fetch localities already on disk")
    ap.add_argument("--verify-only", action="store_true", help="check the files; fetch nothing")
    ap.add_argument("--no-verify", action="store_true", help="skip the completeness check")
    args = ap.parse_args()

    out_root = raw_dir(2025)
    only = {p.upper() for p in args.province}

    driver = open_browser()
    try:
        api = Api(driver)

        print("walking the region tree ...")
        cities = walk_cities(api)
        print(f"{len(cities):,} cities/municipalities")
        if only:
            cities = [c for c in cities if (c[1] or "").upper() in only]
            print(f"--province filter: {len(cities)}")
        if not cities:
            sys.exit("the region tree came back empty - nothing to do")

        if not args.verify_only:
            todo = [c for c in cities
                    if args.force or not path_for(out_root, *c[:3]).exists()]
            print(f"{len(todo):,} to fetch\n")
            fetch_all(api, out_root, todo)

        if args.no_verify:
            return

        print("\nverifying completeness ...")
        bad, on_disk = verify(out_root, cities)
        print(f"  checked {len(on_disk):,} localities on disk")
        if not bad:
            print("  every locality has the full national ballot and a mayor.")
            return

        print(f"  {len(bad)} INCOMPLETE:")
        for (province, city), why in sorted(bad.items()):
            print(f"     {province:<24} {city:<24} {'; '.join(why)}")

        retry = [c for c in cities if (c[1], c[2]) in bad]
        print(f"\n  re-fetching {len(retry)} ...")
        fetch_all(api, out_root, retry)

        bad, _ = verify(out_root, cities)
        if bad:
            # Report it, loudly, rather than paper over it. A gap you report is a completely
            # different object from a gap you never noticed.
            print(f"\n  STILL INCOMPLETE after a re-fetch ({len(bad)}). The gap is in "
                  f"COMELEC's data, not the scraper's:")
            for (province, city), why in sorted(bad.items()):
                print(f"     {province:<24} {city:<24} {'; '.join(why)}")
            sys.exit(1)
        print("  all recovered on the retry.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
