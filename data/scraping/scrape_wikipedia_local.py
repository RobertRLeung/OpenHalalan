"""
Recover local races from Wikipedia's per-province and per-city election articles.

Wikipedia is the only candidate-level source for 2007 (the project has none) and fills 2010
municipalities the COMELEC archive never captured. Each article renders one {{Election box}}
table per race, captioned "<Locality> <office> election"; the office word fixes the geography
(gubernatorial -> province, mayoral -> city). Only single-winner executive races are taken -
governor, vice-governor, mayor, vice-mayor - which is what the map uses; multi-winner council
and board tables and House districts are left for a later pass.

    python data/scraping/scrape_wikipedia_local.py --scrape   # -> data/processed/wikipedia_{2007,2010}.csv.gz

Coverage is whatever editors filled: all 80 provinces for 2007 governors, a scatter of cities and
(where present) municipalities elsewhere. Votes are the official tallies Wikipedia cites.
"""
import argparse, csv, gzip, json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = {y: ROOT / "processed" / f"wikipedia_{y}.csv.gz" for y in (2007, 2010)}
CATS = {2007: "Category:2007 Philippine local elections",
        2010: "Category:2010 Philippine local elections"}
UA = "OpenHalalan/1.0 (election dataset research)"

# caption office word -> canonical position and whether the locality is a province or a city
OFFICE = {
    "gubernatorial": ("GOVERNOR", "province"),
    "vice-gubernatorial": ("VICE GOVERNOR", "province"),
    "vice gubernatorial": ("VICE GOVERNOR", "province"),
    "mayoral": ("MAYOR", "city"),
    "mayoralty": ("MAYOR", "city"),
    "vice mayoral": ("VICE MAYOR", "city"),
    "vice-mayoral": ("VICE MAYOR", "city"),
    "vice mayoralty": ("VICE MAYOR", "city"),
    "vice-mayoralty": ("VICE MAYOR", "city"),
}
CAP_RE = re.compile(r"^(.+?)\s+(" + "|".join(sorted(OFFICE, key=len, reverse=True))
                    + r")\s+elections?$", re.I)


def _api(**params):
    params.update(format="json", formatversion="2")
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for _ in range(4):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read())
        except Exception:
            time.sleep(3)
    return {}


def _members(cat):
    """Article titles in a category, recursing one level into sub-categories."""
    out, sub = [], []
    r = _api(action="query", list="categorymembers", cmtitle=cat, cmlimit="500")
    for m in r.get("query", {}).get("categorymembers", []):
        (sub if m["title"].startswith("Category:") else out).append(m["title"])
    for c in sub:
        r = _api(action="query", list="categorymembers", cmtitle=c, cmlimit="500")
        out += [m["title"] for m in r.get("query", {}).get("categorymembers", [])
                if not m["title"].startswith("Category:")]
    return sorted(set(out))


def _clean(s):
    s = re.sub(r"&#91;.*?&#93;|\[[^\]]*\]", "", s)       # footnote refs [1], [N 29], &#91;3&#93;
    s = re.sub(r"\(incumbent\)", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _cells(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]


def _rows(table):
    """Candidate rows from one election box. Column order varies by article (Candidate|Party or
    Party|Candidate), so read it from the header rather than assume."""
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    ci = pi = vi = None
    for tr in trs:                                        # find the header row
        head = [c.lower() for c in _cells(tr)]
        if "candidate" in head and "party" in head and "votes" in head:
            ci, pi, vi = head.index("candidate"), head.index("party"), head.index("votes")
            break
    if ci is None:
        return
    for tr in trs:
        cells = _cells(tr)
        # data rows carry a leading colour-swatch cell the header lacks, so shift the indices by 1
        if len(cells) == len(head) + 1 and cells[0] == "" and re.fullmatch(r"[\d,]+", cells[vi + 1]):
            yield _clean(cells[ci + 1]), _clean(cells[pi + 1]), int(cells[vi + 1].replace(",", ""))


def _parse(html):
    # A regional or per-province article lists a province's governor, then that province's mayors;
    # the mayoral captions name only the town. Walk the tables in document order and let each
    # gubernatorial table set the province the mayoral tables under it belong to. Towns still left
    # without a province (pure city articles) are placed from a nationwide map at load time.
    current_province = ""
    for m in re.finditer(r"<table[^>]*wikitable[^>]*>(.*?)</table>", html, re.S):
        table = m.group(0)
        cap = re.search(r"<caption>(.*?)</caption>", table, re.S)
        if not cap:
            continue
        text = _clean(re.sub(r"<[^>]+>", "", cap.group(1)))
        hit = CAP_RE.match(text)
        if not hit:
            continue
        # some captions carry a year ("2007 Davao City ...") or embed the province
        # ("Naga, Camarines Sur"); strip the year and split the province out of the town.
        locality = re.sub(r"^20\d\d\s+", "", hit.group(1)).strip().strip(",").strip()
        word = hit.group(2).lower()
        pos, level = OFFICE[word]
        prov_in_caption = ""
        if level == "city" and "," in locality:
            locality, _, prov_in_caption = (p.strip() for p in locality.partition(","))
        if level == "province":
            current_province = locality
        for cand, party, votes in _rows(table):
            yield {"province": locality if level == "province"
                                else (prov_in_caption or current_province),
                   "city": locality if level == "city" else "",
                   "position": pos, "candidate_name": cand, "party": party, "votes": votes}


def scrape():
    for year, cat in CATS.items():
        pages = _members(cat)
        rows = []
        for p in pages:
            r = _api(action="parse", page=p, prop="text")
            html = r.get("parse", {}).get("text", "")
            rows += list(_parse(html))
            time.sleep(0.3)
        OUT[year].parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(OUT[year], "wt", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["province", "city", "position",
                                               "candidate_name", "party", "votes"])
            w.writeheader(); w.writerows(rows)
        races = len({(r["province"], r["city"], r["position"]) for r in rows})
        print(f"{year}: {len(rows):,} candidate rows across {races} races from {len(pages)} articles")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrape", action="store_true")
    a = ap.parse_args()
    if a.scrape:
        scrape()
