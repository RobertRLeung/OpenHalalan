"""
Recover the 2010 election from the archived COMELEC/Smartmatic results site.

The official 2010 results (electionresults.comelec.gov.ph) are gone, but the Internet Archive
captured the per-municipality pages - each a full table per office (Candidate, Party, Votes,
Percentage) for president, VP, senator, party-list, House, governor, vice-governor, board
member, mayor, vice-mayor and councilor. This is the only candidate-level source for 2010's
LOCAL races (the Ianmaps data the project already has is national-only and carries no party).

    python data/scraping/scrape_2010_comelec.py --enumerate   # CDX -> the archived muni URLs
    python data/scraping/scrape_2010_comelec.py --download     # fetch each page (cached, resumable)
    python data/scraping/scrape_2010_comelec.py --parse        # -> data/processed/comelec_2010.csv.gz

Coverage is whatever the Archive kept: ~1,180 of ~1,634 municipalities have a municipality-level
page; the rest are recoverable only by summing precinct pages (a separate pass). Serial fetches
with backoff, cached to disk, resumable.
"""
import argparse, csv, gzip, json, re, time, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data" / "comelec_2010"
URLS = RAW / "_urls.json"                      # {muni_code: timestamp}
OUT = ROOT / "processed" / "comelec_2010.csv.gz"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120 Safari/537.36"
DOMAIN = "electionresults.comelec.gov.ph"


def _get(url, tries=4, timeout=60):
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                          timeout=timeout).read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(3)
    return ""


def _muni_kind(code):
    # region 97xxxxx, province ...00000, municipality ...000 (else precinct)
    if code.startswith("97") and len(code) == 7:
        return "region"
    if code.endswith("00000"):
        return "province"
    return "municipality" if code.endswith("000") else "precinct"


def enumerate_munis():
    """CDX -> {municipality code: best (latest) 200 snapshot timestamp}."""
    q = "http://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode({
        "url": f"{DOMAIN}/res_reg*", "output": "json", "fl": "original,timestamp,statuscode",
        "collapse": "urlkey", "filter": "statuscode:200", "limit": "300000"})
    for _ in range(6):
        rows = _get(q, tries=1, timeout=180)
        if rows:
            break
        time.sleep(10)
    rows = json.loads(rows)[1:] if rows else []
    best = {}
    for orig, ts, _sc in rows:
        m = re.search(r"res_reg(\d+)\.html", orig)
        if m and _muni_kind(m.group(1)) == "municipality":
            best[m.group(1)] = max(best.get(m.group(1), ""), ts)
    RAW.mkdir(parents=True, exist_ok=True)
    URLS.write_text(json.dumps(best))
    print(f"enumerated {len(best):,} archived municipality pages")
    return best


def download():
    best = json.loads(URLS.read_text()) if URLS.exists() else enumerate_munis()
    RAW.mkdir(parents=True, exist_ok=True)
    done = 0
    for i, (code, ts) in enumerate(sorted(best.items())):
        out = RAW / f"{code}.html"
        if out.exists() and out.stat().st_size > 2000:
            done += 1
            continue
        url = f"https://web.archive.org/web/{ts}id_/http://{DOMAIN}/res_reg{code}.html"
        html = _get(url)
        if "ContestTitle" in html:
            out.write_text(html, encoding="utf-8")
            done += 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(best)} fetched ({done} on disk)", flush=True)
        time.sleep(0.25)
    print(f"downloaded: {done} municipality pages on disk")


# office string -> (canonical position, province, city, district)
def _office(label):
    s = re.sub(r"\s+", " ", label).strip()
    head, _, tail = s.partition(" of ")
    head = head.strip().upper()
    pos = {
        "PRESIDENT": "PRESIDENT", "VICE-PRESIDENT": "VICE PRESIDENT", "SENATOR": "SENATOR",
        "PARTY LIST": "PARTY LIST", "MEMBER, HOUSE OF REPRESENTATIVES": "MEMBER, HOUSE OF REPRESENTATIVES",
        "PROVINCIAL GOVERNOR": "GOVERNOR", "PROVINCIAL VICE-GOVERNOR": "VICE GOVERNOR",
        "MEMBER, SANGGUNIANG PANLALAWIGAN": "PROVINCIAL BOARD MEMBER",
        "MAYOR": "MAYOR", "VICE-MAYOR": "VICE MAYOR", "MEMBER, SANGGUNIANG BAYAN": "COUNCILOR",
    }.get(head)
    parts = [p.strip() for p in tail.split(" - ")]
    prov = parts[0] if parts and parts[0] != "PHILIPPINES" else ""
    city = district = ""
    for p in parts[1:]:
        if re.search(r"DIST|LEGDIST|PROVDIST", p):
            district = re.sub(r"\s*(LEG|PROV)?DIST.*$", "", p).strip()
        else:
            city = p
    return pos, prov, city, district


def parse():
    rows = []
    files = sorted(RAW.glob("*.html"))
    for f in files:
        html = f.read_text(errors="ignore")
        parts = re.split(r'<a[^>]*id="ContestTitle"[^>]*>(.*?)</a>', html)
        offices = [(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", parts[k])).strip(),
                    parts[k + 1] if k + 1 < len(parts) else "")
                   for k in range(1, len(parts), 2)]
        # The page is ONE municipality, but only its local contests name it ("MAYOR of ABRA -
        # BANGUED"); the national ones say "PRESIDENT of PHILIPPINES". Take the locality from a
        # local contest and stamp it on every row, so president/senator get the town they were
        # tallied in.
        page_prov = page_city = ""
        for office, _ in offices:
            pos, prov, city, _d = _office(office)
            if pos in ("MAYOR", "VICE MAYOR", "COUNCILOR") and city:
                page_prov, page_city = prov, city
                break
        for office, body in offices:
            pos, _prov, _city, _district = _office(office)
            if not pos:
                continue
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
                td = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                      for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if len(td) >= 4 and td[0] and td[0].lower() != "candidate":
                    # keep the raw office label so the build's split_position derives the canonical
                    # position and district exactly as it does for every other feed
                    rows.append({"province": page_prov, "city": page_city, "office": office,
                                 "candidate_name": td[0], "party": td[1],
                                 "votes": td[2].replace(",", ""), "percentage": td[3].replace("%", "")})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["province", "city", "office",
                                           "candidate_name", "party", "votes", "percentage"])
        w.writeheader(); w.writerows(rows)
    munis = len({(r["province"], r["city"]) for r in rows if r["city"]})
    print(f"parsed {len(rows):,} rows from {len(files)} pages; {munis} distinct municipalities")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--enumerate", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    a = ap.parse_args()
    if a.enumerate:
        enumerate_munis()
    if a.download:
        download()
    if a.parse:
        parse()
