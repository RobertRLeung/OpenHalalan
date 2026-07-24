"""
Reconstruct 2013 candidate-level vote counts from Rappler's archived results.

    https://web.archive.org/web/2013*/http://election-results.rappler.com/2013/

Rappler's 2013 "Comelec Live Data" site is gone, but the Internet Archive captured most of the
municipality pages (plus provinces and a national senate page) as server-rendered
HTML - each carrying every candidate, party and vote total. That is a near-complete
candidate-level record for a cycle the project otherwise has NO vote data for (our vote counts
start in 2016).

    python data/scraping/scrape_2013_rappler.py --urls      # enumerate captured pages (CDX)
    python data/scraping/scrape_2013_rappler.py --download   # fetch raw HTML into the cache
    python data/scraping/scrape_2013_rappler.py --parse      # cache -> data/processed/rappler_2013.csv

Politeness: the Wayback Machine throttles, so fetches are serial with backoff and cached to
disk, so re-runs are cheap and resumable.
"""
import argparse
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "election-results.rappler.com"
CDX = ("http://web.archive.org/cdx/search/cdx?url=" + HOST +
       "*&output=text&fl=original,timestamp&filter=statuscode:200&filter=mimetype:text/html"
       "&collapse=urlkey&limit=40000")
WB = "https://web.archive.org/web/{ts}id_/{url}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

RAW = Path(__file__).resolve().parents[1] / "raw_data" / "rappler_2013"
URLS = RAW / "_urls.tsv"


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def enumerate_urls():
    """Captured 2013 result pages, one timestamp each: municipalities, provinces, senate."""
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in _get(CDX, timeout=120).splitlines():
        try:
            original, ts = line.split(" ")
        except ValueError:
            continue
        # keep only the 2013 result pages (the path has a stray %20 before 2013)
        if re.search(r"/(?:%20)?2013/", original) and "/precinct" not in original:
            rows.append((original, ts))
    # de-dup by original, keep the first (CDX already collapsed by urlkey)
    seen, out = set(), []
    for orig, ts in rows:
        key = re.sub(r"^https?://[^/]+", "", orig).rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append((orig, ts))
    URLS.write_text("\n".join(f"{o}\t{t}" for o, t in out), encoding="utf-8")
    depth = lambda o: o.rstrip("/").count("/") - 3
    munis = sum(1 for o, _ in out if re.search(r"/2013/[^/]+/[^/]+/[^/]+$", o.replace("%20", "")))
    print(f"{len(out)} pages ({munis} municipality-depth) -> {URLS.name}")
    return out


def _slug(url):
    path = re.sub(r"^https?://[^/]+/", "", url).replace("%20", "").strip("/")
    return re.sub(r"[^A-Za-z0-9]+", "_", path) + ".html"


def download(force=False):
    RAW.mkdir(parents=True, exist_ok=True)
    urls = [ln.split("\t") for ln in URLS.read_text().splitlines()] if URLS.exists() else enumerate_urls()
    if URLS.exists() and not isinstance(urls[0], (list, tuple)):
        urls = [ln.split("\t") for ln in URLS.read_text().splitlines()]
    got = skipped = failed = 0
    for i, (url, ts) in enumerate(urls):
        out = RAW / _slug(url)
        if out.exists() and out.stat().st_size > 500 and not force:
            skipped += 1
            continue
        for attempt in range(4):
            try:
                out.write_text(_get(WB.format(ts=ts, url=url)), encoding="utf-8")
                got += 1
                break
            except Exception as e:
                if attempt == 3:
                    failed += 1
                    print(f"  FAIL {url}: {e}")
                else:
                    time.sleep(2 * (attempt + 1))
        time.sleep(0.4)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(urls)}  got {got} skip {skipped} fail {failed}", flush=True)
    print(f"done: got {got}, cached {skipped}, failed {failed}")


# ----------------------------------------------------------------- parse
# Each page renders one <table> per race under a "<p>POSITION of PLACE</p>" header, rows of
# Candidate | Party | Votes. Municipality pages carry the municipal races (mayor/vice/councilor);
# province pages the provincial ones; the senate page the national slate. Region/province/city
# come off the URL path, so a race is only kept from the page whose level it belongs to.
LOCAL = {"MAYOR", "VICE-MAYOR", "VICE MAYOR", "COUNCILOR", "MEMBER, SANGGUNIANG BAYAN",
         "MEMBER, SANGGUNIANG PANLUNGSOD"}
# Rappler labels the top provincial offices "PROVINCIAL GOVERNOR" / "PROVINCIAL VICE-GOVERNOR"
# and the district seat "MEMBER, HOUSE OF REPRESENTATIVES" - all of which must be whitelisted
# or governor (a province-level map race), vice-governor and the House are silently dropped.
PROVINCIAL = {"GOVERNOR", "PROVINCIAL GOVERNOR", "VICE-GOVERNOR", "VICE GOVERNOR",
              "PROVINCIAL VICE-GOVERNOR", "PROVINCIAL BOARD MEMBER",
              "MEMBER, SANGGUNIANG PANLALAWIGAN", "MEMBER, HOUSE OF REPRESENTATIVES"}


def _path_parts(url):
    p = re.sub(r"^https?://[^/]+/", "", url).replace("%20", "").strip("/")
    parts = p.split("/")
    return parts[1:] if parts and parts[0] == "2013" else parts


def _races(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tbl in soup.select("div.phvote-tbl table"):
        # the header is "POSITION of PLACE" (position all-caps); skip the "As of <date>" stamp
        hdr = tbl.find_previous(
            lambda t: t.name == "p" and re.match(r"[A-Z][A-Z ,./-]* of ", t.get_text().strip()))
        if not hdr:
            continue
        m = re.match(r"\s*([A-Z][A-Z ,./-]*?)\s+of\s+(.+)", hdr.get_text().strip())
        if not m:
            continue
        position = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        # "of KALINGA - FIRST PROVDIST" -> the qualifier keeps the district so House and
        # multi-district provincial-board contests do not collapse into one merged race.
        area = re.sub(r"\s+", " ", m.group(2)).strip().upper()
        rows = []
        for tr in tbl.select("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text()).strip() for td in tr.select("td")]
            if len(cells) >= 3 and cells[0]:
                name = re.sub(r"\s*\([^)]*\)\s*$", "", cells[0]).strip()  # drop "(PARTY)" suffix
                votes = cells[2].replace(",", "")
                if votes.isdigit():
                    rows.append((name, cells[1].strip(), int(votes)))
        if rows:
            out.append((position, area, rows))
    return out


def parse():
    import csv
    urls = dict(ln.split("\t") for ln in URLS.read_text().splitlines()) if URLS.exists() else {}
    by_slug = {_slug(u): u for u in urls}
    rows = []
    for f in sorted(RAW.glob("*.html")):
        url = by_slug.get(f.name)
        if not url:
            continue
        parts = _path_parts(url)
        for position, area, cands in _races(f.read_text(encoding="utf-8", errors="ignore")):
            if len(parts) >= 3 and position in LOCAL:            # municipality page, municipal race
                region, province, city = parts[0], parts[1], parts[2]
            elif len(parts) == 2 and position in PROVINCIAL:      # province page, provincial race
                region, province, city = parts[0], parts[1], ""
            elif position in ("SENATOR", "PARTY-LIST"):
                region, province, city = "", "", ""
            else:
                continue
            for name, party, votes in cands:
                rows.append({"year": 2013, "region": region, "province": province, "city": city,
                             "position": position, "area": area, "candidate_name": name,
                             "party": party, "votes": votes})
    out = RAW.parents[1] / "processed" / "rappler_2013.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["year", "region", "province", "city", "position",
                                           "area", "candidate_name", "party", "votes"])
        w.writeheader()
        w.writerows(rows)
    print(f"parsed {len(rows):,} candidate-rows from {len(list(RAW.glob('*.html'))):,} pages -> {out.name}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--parse", action="store_true")
    args = ap.parse_args()
    if args.urls:
        enumerate_urls()
    if args.download:
        download(force=args.force)
    if args.parse:
        parse()
