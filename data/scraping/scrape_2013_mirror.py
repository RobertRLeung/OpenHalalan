"""
Recover missing 2013 municipalities from Rappler's /2010/ result pages.

The pages sit at /2010/ URLs but hold 2013 data: the Internet Archive only captured them in
2016-2018, by which time Rappler served 2013 content there. Three checks confirm it:

  * 2010 was a presidential election, yet these pages carry no presidential race;
  * overlapping municipalities byte-match the /2013/ scrape; and
  * the governors are the 2013 winners (Ilocos Sur = Singson, not 2010's Savellano).

So this is a second mirror of 2013, and it covers provinces whose /2013/ pages were never
archived. The layout is the same, so the 2013 parser is reused. Output feeds
build_vote_counts.load_2013(), where the primary /2013/ scrape wins any overlap. 2010 itself
stays national-only, from the Ianmaps source.

    python data/scraping/scrape_2013_mirror.py --urls / --download / --parse
      -> data/processed/rappler_2013_mirror.csv

Serial fetches with backoff, cached to disk, resumable.
"""
import argparse
import csv
import re
import time
import urllib.request
from pathlib import Path

# Reuse the 2013 machinery: the page layout and office sets are identical across cycles.
import scrape_2013_rappler as S

HOST = "election-results.rappler.com"
CDX = ("http://web.archive.org/cdx/search/cdx?url=" + HOST + "&matchType=domain"
       "&output=text&fl=original,timestamp&collapse=urlkey"
       "&filter=statuscode:200&filter=mimetype:text/html"
       "&filter=original:.*/(%20)?2010/.*&limit=60000")

RAW = Path(__file__).resolve().parents[1] / "raw_data" / "rappler_2010"
URLS = RAW / "_urls.tsv"


def enumerate_urls():
    RAW.mkdir(parents=True, exist_ok=True)
    seen, out = set(), []
    for line in S._get(CDX, timeout=180).splitlines():
        try:
            original, ts = line.split(" ")
        except ValueError:
            continue
        if re.search(r"/(?:%20)?2010/", original) and "/precinct" not in original:
            key = re.sub(r"^https?://[^/]+", "", original).replace("%20", "").rstrip("/")
            if key and key not in seen:
                seen.add(key)
                out.append((original, ts))
    URLS.write_text("\n".join(f"{o}\t{t}" for o, t in out), encoding="utf-8")
    munis = sum(1 for o, _ in out
                if re.match(r"[^/]+/2010/[^/]+/[^/]+/[^/]+$", o.replace("%20", "").split("//")[-1]))
    print(f"{len(out)} pages ({munis} municipality-depth) -> {URLS.name}")
    return out


def download(force=False):
    RAW.mkdir(parents=True, exist_ok=True)
    urls = [ln.split("\t") for ln in URLS.read_text().splitlines()] if URLS.exists() else enumerate_urls()
    got = skipped = failed = 0
    for i, (url, ts) in enumerate(urls):
        out = RAW / S._slug(url)
        if out.exists() and out.stat().st_size > 500 and not force:
            skipped += 1
            continue
        for attempt in range(4):
            try:
                out.write_text(S._get(S.WB.format(ts=ts, url=url)), encoding="utf-8")
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


def _path_parts(url):
    p = re.sub(r"^https?://[^/]+/", "", url).replace("%20", "").strip("/").split("/")
    return p[1:] if p and p[0] == "2010" else p


def parse():
    urls = dict(ln.split("\t") for ln in URLS.read_text().splitlines()) if URLS.exists() else {}
    by_slug = {S._slug(u): u for u in urls}
    rows = []
    for f in sorted(RAW.glob("*.html")):
        url = by_slug.get(f.name)
        if not url:
            continue
        parts = _path_parts(url)
        for position, area, cands in S._races(f.read_text(encoding="utf-8", errors="ignore")):
            if len(parts) >= 3 and position in S.LOCAL:
                region, province, city = parts[0], parts[1], parts[2]
            elif len(parts) == 2 and position in S.PROVINCIAL:
                region, province, city = parts[0], parts[1], ""
            else:
                continue                      # skip national races - Ianmaps carries those
            for name, party, votes in cands:
                rows.append({"year": 2013, "region": region, "province": province, "city": city,
                             "position": position, "area": area, "candidate_name": name,
                             "party": party, "votes": votes})
    out = RAW.parents[1] / "processed" / "rappler_2013_mirror.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["year", "region", "province", "city", "position",
                                           "area", "candidate_name", "party", "votes"])
        w.writeheader()
        w.writerows(rows)
    munis = len({(r["province"], r["city"]) for r in rows if r["city"]})
    print(f"parsed {len(rows):,} candidate-rows, {munis} municipalities -> {out.name}")
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
