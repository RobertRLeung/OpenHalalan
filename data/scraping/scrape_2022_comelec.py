"""
Scrape the 2022 COMELEC results into data/raw_data/2022/ from COMELEC's JSON API.

    python data/scraping/scrape_2022_comelec.py
    python data/scraping/scrape_2022_comelec.py --province "ILOCOS NORTE"

NO BROWSER. The site is an AngularJS front end over a static JSON API, so this is plain
HTTP: fast, resumable, concurrent, and - the point - COMPLETE.

Why this replaces the Selenium scraper
--------------------------------------
The old scraper drove a real browser and read the rendered results table. It captured only
the rows the page had rendered, so long candidate lists were silently TRUNCATED. The 2022
presidential race shipped with 7 of its 10 candidates: it kept the first seven
alphabetically and dropped MONTEMAYOR, PACQUIAO and ROBREDO - the second-place finisher,
with ~15 million votes. Every municipality was affected, so the loss was invisible in a
coverage check: all 1,634 files existed, each just missing the same three people.

The API returns every ballot option, so the truncation cannot recur.

The API
-------
  data/regions/root.json          the location tree: country -> region -> province ->
                                  city/municipality -> barangay. Each node carries `srs`
                                  (children) and `pps` (boards of canvassers).

  data/results/{url}.json         a board's canvassed results: one row per (contest,
                                  ballot option) with the vote count. A city's MUNICIPAL
                                  BOARD OF CANVASSERS (MBOC) holds its city-wide totals.

  data/contests/{cc}.json         a contest: its name, and EVERY ballot option on it, with
                                  each candidate's name and party.

Output: data/raw_data/2022/{REGION}/{PROVINCE}/{REGION}_{PROVINCE}_{CITY}.csv, the same
schema as every other cycle, so the compile step handles it unchanged.
"""

import argparse
import csv
import json
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

from config import raw_dir

BASE = "https://2022electionresults.comelec.gov.ph"
ROOT = "data/regions/root.json"

# The location tree, cached. Not the results - those are written to raw_data/ and are the
# actual output. Safe to delete at any time; it only costs the walk again.
TREE_CACHE = Path(__file__).resolve().parent / ".tree_cache_2022"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": f"{BASE}/",
    "Accept": "application/json, text/plain, */*",
}

FIELDS = ["region", "province", "city", "position", "rank",
          "candidate_name", "party", "votes", "percentage"]

# COMELEC glues the party abbreviation onto the candidate name -
# "PACQUIAO, MANNY PACMAN(PROMDI)" - while the contest's own `pn` gives the party's full
# name ("ABAG PROMDI"). Every other cycle records the abbreviation, so take it from the
# name and fall back to the full name.
_PARTY_SUFFIX = re.compile(r"\(([^)]{1,20})\)\s*$")


def safe(name):
    """Filesystem-safe upper-case token, matching the other scrapes' convention."""
    return str(name).upper().replace(" ", "_").replace("/", "_").replace(",", "")


class Api:
    """Thread-safe client. COMELEC's S3 throttles, so every fetch backs off and retries."""

    def __init__(self):
        self._local = threading.local()
        self._contests = {}
        self._lock = threading.Lock()

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
        return self._local.session

    def get(self, path, retries=6):
        # The location tree is ~1,700 nodes and has to be walked in full before a single
        # result can be fetched, even to re-fetch one city. It is also static - the 2022
        # election is over. So it is cached on disk: the first run pays the eight minutes,
        # every run after that starts immediately. Delete TREE_CACHE (or pass
        # --refresh-tree) to re-walk. Only the tree is cached, never the results.
        cached = None
        if path.startswith("data/regions/"):
            cached = TREE_CACHE / (path[len("data/regions/"):].replace("/", "_"))
            if cached.exists():
                try:
                    return json.loads(cached.read_text())
                except ValueError:
                    cached.unlink()          # a half-written file from an interrupted run

        for attempt in range(retries):
            try:
                r = self.session.get(f"{BASE}/{path}", timeout=30)
                if r.ok:
                    data = r.json()
                    if cached is not None:
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        cached.write_text(json.dumps(data))
                    return data
                # 403 here is throttling, not absence - back off rather than give up.
            except Exception:
                pass
            time.sleep(1.5 * (attempt + 1))
        return None

    def contest(self, code):
        """Contest definition, cached: its name and every ballot option on it."""
        with self._lock:
            if code in self._contests:
                return self._contests[code]

        data = self.get(f"data/contests/{code}.json")

        with self._lock:
            self._contests[code] = data
        return data


# A province whose canvass sits on the PROVINCE node rather than on its children, and the
# name the resulting locality should carry. See walk_cities for how these are detected -
# the detection is general; only the display name is hardcoded.
PROVINCE_IS_A_CITY = {"NCR - MANILA": "CITY OF MANILA"}


def walk_cities(api):
    """Every locality that actually has a board of canvassers, with its region and province.

    Nearly always that is a City/Municipality node. Manila is the exception, and it is the
    reason this function is not four lines long.

    COMELEC models the City of Manila as a PROVINCE ("NCR - MANILA") whose fourteen
    children - Tondo, Binondo, Ermita, Sampaloc... - are its districts, filed under
    can="City/Municipality". None of those fourteen is a canvass unit: they carry no board
    at all. Manila's single board hangs off the province node itself. A walk that only ever
    reads boards off City/Municipality nodes therefore returns fourteen empty districts and
    no Manila - which is exactly what the first run of this scraper did, dropping the
    country's second-largest city.

    But "province node has a board -> treat it as a city" is WRONG, and expensively so.
    TAGUIG - PATEROS is also a province node with a board, and Taguig and Pateros each have
    their own board underneath it. Its province-level board is a district canvass sitting
    ON TOP of theirs, so emitting it would count Taguig and Pateros twice.

    The rule that distinguishes them: a province is itself the canvass unit only when it
    has a board AND NONE of its children do.
    """
    root = api.get(ROOT)
    if not root:
        sys.exit("could not load the region tree")

    cities = []

    def has_board(node):
        return any(board.get("vbs") for board in (node.get("pps") or []))

    def descend(node, region, province):
        level = node.get("can")
        name = node.get("rn")

        if level == "Region":
            region = name
        elif level == "City/Municipality":
            cities.append((region, province, name, node))
            return  # do not descend into barangays: the city's MBOC has its totals

        children = []
        for child in (node.get("srs") or {}).values():
            fetched = api.get(f"data/regions/{child['url']}.json")
            if fetched:
                children.append(fetched)

        if level == "Province":
            province = name
            if has_board(node) and not any(has_board(c) for c in children):
                cities.append((region, province,
                               PROVINCE_IS_A_CITY.get(name, name), node))
                return

        for child in children:
            descend(child, region, province)

    # root.json is a pointer to the country node; follow it if it points elsewhere.
    country = api.get(f"data/regions/{root['url']}.json") if root.get("url") else root
    descend(country or root, None, None)
    return cities


def city_rows(api, region, province, city, node):
    """Every contest on this city's ballot, from its board of canvassers."""
    rows = []

    for board in node.get("pps", []):
        for vb in board.get("vbs", []):
            results = api.get(f"data/results/{vb['url']}.json")
            if not results:
                continue

            # Group the board's rows by contest.
            by_contest = {}
            for r in results.get("rs", []):
                by_contest.setdefault(r["cc"], []).append(r)

            for code, entries in by_contest.items():
                contest = api.contest(code)
                if not contest:
                    continue

                # Every ballot option on the contest, so nothing can be truncated.
                options = {b["boc"]: b for b in contest.get("bos", [])}

                tallied = []
                for e in entries:
                    option = options.get(e["bo"])
                    if not option:
                        continue
                    name = option["bon"].strip()
                    match = _PARTY_SUFFIX.search(name)
                    party = match.group(1).strip() if match else (option.get("pn") or "")
                    tallied.append((name, party, int(e.get("v") or 0),
                                    e.get("per") or ""))

                # COMELEC does not rank; sort by votes so `rank` means what it says.
                tallied.sort(key=lambda t: t[2], reverse=True)

                for i, (name, party, votes, pct) in enumerate(tallied, 1):
                    rows.append({
                        "region": region,
                        "province": province,
                        "city": city,
                        "position": contest["cn"],
                        "rank": i,
                        "candidate_name": name,
                        "party": party,
                        "votes": votes,
                        "percentage": f"{pct} %" if pct != "" else "",
                    })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Scrape COMELEC 2022 into data/raw_data/2022/")
    ap.add_argument("--province", action="append", default=[])
    ap.add_argument("--force", action="store_true", help="re-fetch cities already on disk")
    ap.add_argument("--refresh-tree", action="store_true",
                    help="discard the cached location tree and walk COMELEC again")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent cities (default 8; COMELEC's S3 throttles)")
    args = ap.parse_args()

    only = {p.upper() for p in args.province}
    out_root = raw_dir(2022)

    if args.refresh_tree and TREE_CACHE.exists():
        shutil.rmtree(TREE_CACHE)

    api = Api()

    cached = TREE_CACHE.exists()
    print("reading the cached region tree..." if cached else
          "walking the region tree (~1,700 nodes; slow, but cached for next time)...")
    cities = walk_cities(api)
    print(f"{len(cities):,} cities/municipalities")

    if only:
        cities = [c for c in cities if (c[1] or "").upper() in only]
        print(f"--province filter: {len(cities)}")

    todo = []
    for region, province, city, node in cities:
        path = (out_root / safe(region) / safe(province) /
                f"{safe(region)}_{safe(province)}_{safe(city)}.csv")
        if path.exists() and not args.force:
            continue
        todo.append((region, province, city, node, path))

    print(f"{len(todo):,} to fetch\n")

    scraped, empty = 0, []
    lock = threading.Lock()

    def work(item):
        region, province, city, node, path = item
        rows = city_rows(api, region, province, city, node)
        if not rows:
            return city, province, None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        return city, province, len(rows)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, i) for i in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            city, province, rows = fut.result()
            with lock:
                if rows is None:
                    empty.append(f"{city}, {province}")
                else:
                    scraped += 1
                if n % 50 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}  scraped={scraped} empty={len(empty)}",
                          flush=True)

    print(f"\nDone. scraped={scraped} empty={len(empty)}")
    if empty:
        # Never hide a gap.
        print(f"\n{len(empty)} cities returned no results:")
        for e in sorted(empty):
            print(f"  - {e}")


if __name__ == "__main__":
    main()
