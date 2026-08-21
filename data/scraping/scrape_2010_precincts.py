"""
Sum 2010 precinct pages into municipal totals for towns the Archive kept only precinct-by-precinct.

NOT wired into the build: the output is not trustworthy. The Archive captured only a sparse,
uneven fraction of each municipality's precincts, so a summed "municipal total" is really a
partial sample - Davao City and Manila come out at under 3% of their true electorate, San Luis
at ~4%. With no registered-voter or true-precinct count to measure completeness against, there
is no honest gate (got/archived looks high precisely where the Archive kept fewest precincts),
and a partial sum can flip the plurality winner. Kept as a documented dead-end.

    python data/scraping/scrape_2010_precincts.py --download   # fetch precinct pages (cached)
    python data/scraping/scrape_2010_precincts.py --parse      # -> data/processed/comelec_2010_precincts.csv.gz

Precinct code -> municipality code by zeroing the last three digits. _prec_snaps.json (written by
the enumeration step) lists only precincts whose municipality has no usable municipality page.
"""
import argparse, csv, gzip, json, re, time, urllib.request
from collections import defaultdict
from pathlib import Path

from scrape_2010_comelec import _office, DOMAIN, UA  # reuse office parsing

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data" / "comelec_2010_precincts"
SNAPS = ROOT / "raw_data" / "comelec_2010" / "_prec_snaps.json"   # {precinct_code: timestamp}
OUT = ROOT / "processed" / "comelec_2010_precincts.csv.gz"


def _get(url, tries=4, timeout=60):
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                          timeout=timeout).read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(3)
    return ""


def download():
    snaps = json.loads(SNAPS.read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    done = 0
    for i, (code, ts) in enumerate(sorted(snaps.items())):
        out = RAW / f"{code}.html"
        if out.exists() and out.stat().st_size > 2000:
            done += 1
            continue
        html = _get(f"https://web.archive.org/web/{ts}id_/http://{DOMAIN}/res_reg{code}.html")
        if "ContestTitle" in html:
            out.write_text(html, encoding="utf-8")
            done += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(snaps)} fetched ({done} on disk)", flush=True)
        time.sleep(0.2)
    print(f"downloaded: {done} precinct pages on disk")


def _page_rows(html):
    """(office label, candidate, party, votes) for every candidate row on one precinct page."""
    parts = re.split(r'<a[^>]*id="ContestTitle"[^>]*>(.*?)</a>', html)
    for k in range(1, len(parts), 2):
        office = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", parts[k])).strip()
        body = parts[k + 1] if k + 1 < len(parts) else ""
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            td = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                  for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(td) >= 3 and td[0] and td[0].lower() != "candidate":
                votes = re.sub(r"[^0-9]", "", td[2])
                yield office, td[0], td[1], int(votes) if votes else 0


# Keep a municipality only if we captured this fraction of its archived precincts. A partial
# sum understates every candidate and can flip the plurality winner; a low bar would ship a
# wrong winner, which is worse on the map than leaving the town blank.
COVERAGE_MIN = 0.80


def _archived_precincts_per_muni():
    snaps = json.loads((ROOT / "raw_data" / "comelec_2010" / "_all_snaps.json").read_text())
    per = defaultdict(int)
    for code in snaps:
        if not (code.endswith("000") or (code.startswith("97") and len(code) == 7)):
            per[code[:-3] + "000"] += 1                 # precinct -> its municipality
    return per


def parse():
    # muni code -> {(office, candidate, party): summed votes}
    tally = defaultdict(lambda: defaultdict(int))
    # muni code -> (province, city) taken from a local contest on any of its precinct pages
    locality = {}
    got = defaultdict(int)                               # muni code -> precinct pages summed
    files = sorted(RAW.glob("*.html"))
    for f in files:
        muni = f.stem[:-3] + "000"
        got[muni] += 1
        html = f.read_text(errors="ignore")
        for office, cand, party, votes in _page_rows(html):
            pos, prov, city, _d = _office(office)
            if not pos:
                continue
            if muni not in locality and pos in ("MAYOR", "VICE MAYOR", "COUNCILOR") and city:
                locality[muni] = (prov, city)
            tally[muni][(office, cand, party)] += votes

    archived = _archived_precincts_per_muni()
    kept, dropped = [], []
    for muni in tally:
        ratio = got[muni] / archived[muni] if archived.get(muni) else 0
        (kept if ratio >= COVERAGE_MIN else dropped).append((muni, ratio))
    kept_set = {m for m, _ in kept}

    rows = []
    for muni, cands in tally.items():
        if muni not in kept_set or muni not in locality:  # need both coverage and a named town
            continue
        prov, city = locality[muni]
        for (office, cand, party), votes in cands.items():
            rows.append({"province": prov, "city": city, "office": office,
                         "candidate_name": cand, "party": party, "votes": votes, "percentage": ""})
    print(f"dropped {len(dropped)} municipalities below {COVERAGE_MIN:.0%} precinct coverage; "
          f"kept {len(kept)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["province", "city", "office",
                                           "candidate_name", "party", "votes", "percentage"])
        w.writeheader(); w.writerows(rows)
    munis = len({(r["province"], r["city"]) for r in rows if r["city"]})
    print(f"parsed {len(rows):,} summed rows from {len(files)} precinct pages; {munis} municipalities")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    a = ap.parse_args()
    if a.download:
        download()
    if a.parse:
        parse()
