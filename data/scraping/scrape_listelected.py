"""
Scrape COMELEC's official "List of Elected Candidates" PDFs into raw text.

    https://www.comelec.gov.ph/?r=ListElectedCandidates

That page is an accordion of PDF links, three per cycle (City/Municipal, House of
Representatives, Provincial) for 2001, 2004, 2007, 2010, 2013, 2016, 2019, 2022. The PDFs
are text-based (not scans) and, unlike the vote-count scrapes, carry a SEX column and reach
back to 2001 - two things the rest of the dataset does not have.

    python data/scraping/scrape_listelected.py --download   # fetch the 24 PDFs
    python data/scraping/scrape_listelected.py --dump 2001_provincial   # extracted text

The PDFs sit on the main comelec.gov.ph host (no Cloudflare challenge on the attachments),
so a plain HTTP GET works; only the results API (2025) needs a browser.
"""
import argparse
import time
import urllib.request
from pathlib import Path

BASE = "https://www.comelec.gov.ph/php-tpls-attachments/ListElectedCandidates"
RAW = Path(__file__).resolve().parents[1] / "raw_data" / "comelec_lec"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# (year, category, exact upstream filename). Filenames are gloriously inconsistent, so they
# are pinned verbatim from the page rather than templated.
FILES = [
    (2001, "citymun",    "2001_list_of_elected_citymunicipal_candidates.pdf"),
    (2001, "house",      "2001_list_of_elected_member_house_of_representatives.pdf"),
    (2001, "provincial", "2001_list_of_elected_provincial_candidates.pdf"),
    (2004, "citymun",    "2004_list_of_elected_citymun_candidates.pdf"),
    (2004, "house",      "2004_list_of_elected_member_house_of_representatives.pdf"),
    (2004, "provincial", "2004_list_of_elected_provincial_candidates.pdf"),
    (2007, "citymun",    "2007_list_of_elected_city_municipal_candidates.pdf"),
    (2007, "house",      "2007_list_of_elected__member__house_of_representatives.pdf"),
    (2007, "provincial", "2007_list_of_elected_provincial_candidates.pdf"),
    (2010, "citymun",    "2010_list_of_elected_citymunicipal_candidates.pdf"),
    (2010, "house",      "2010_list_of_elected_member_house_of_representatives.pdf"),
    (2010, "provincial", "2010_list_of_elected_provincial_candidates.pdf"),
    (2013, "citymun",    "2013_list_of_elected_citymunicipal_candidates.pdf"),
    (2013, "house",      "2013_list_of_elected_member__house_of_representatives.pdf"),
    (2013, "provincial", "2013_list_of_elected_provincial_candidates.pdf"),
    (2016, "citymun",    "2016_list_of_elected_citymunicipal_candidates.pdf"),
    (2016, "house",      "2016_list_of_elected_member__house_of_representives_candidates.pdf"),
    (2016, "provincial", "2016_list_of_elected_provincial_candidates.pdf"),
    (2019, "citymun",    "2019_list_of_elected_citymun_candidates.pdf"),
    (2019, "house",      "2019_list_of_elected_member__house_of_representaives.pdf"),
    (2019, "provincial", "2019_list_of_elected_provincial_candidates_nameonly.pdf"),
    (2022, "citymun",    "2022_list_of_elected_citymunicipal_candidates.pdf"),
    (2022, "house",      "2022_list_of_elected_member__house_of_representatives.pdf"),
    (2022, "provincial", "2022_list_of_elected_provincial_candidates.pdf"),
]


def local_path(year, cat):
    return RAW / f"{year}_{cat}.pdf"


def download(force=False):
    RAW.mkdir(parents=True, exist_ok=True)
    for year, cat, fname in FILES:
        out = local_path(year, cat)
        if out.exists() and not force:
            print(f"  have {out.name} ({out.stat().st_size/1e6:.1f} MB)")
            continue
        req = urllib.request.Request(f"{BASE}/{fname}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as r:
            out.write_bytes(r.read())
        print(f"  got {out.name} ({out.stat().st_size/1e6:.1f} MB)")
        time.sleep(0.5)


def dump(key):
    """Print extracted text of one PDF, e.g. key='2001_provincial'."""
    import fitz
    doc = fitz.open(RAW / f"{key}.pdf")
    for pno in range(doc.page_count):
        print(f"\n===== page {pno+1}/{doc.page_count} =====")
        print(doc[pno].get_text())
    doc.close()


# ----------------------------------------------------------------- parse (citymun)
# The PDF text linearises the table one cell per line. The reliable anchor is SEX: every
# candidate ends in an "M"/"F" line, and the party is always the line right before it. Region
# is a bare roman numeral (or ARMM/CAR/CARAGA/NCR); the province is the line before the region;
# the city is the line before the first position. Names may wrap over two lines.
import re

CITYMUN_POS = {"MAYOR", "VICE-MAYOR", "COUNCILOR"}
NUM_REGIONS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII"}
_JUNK_PREFIX = ("Republic of the", "COMMISSION ON", "Intramuros", "Records and", "LIST OF ELECTED",
                "May ", "Page ", "Notice", "All authorized", "including other", "conformity",
                "Privacy", "account", "and its Impl", "similarly bound")
_JUNK_LABELS = {"REGION :", "SEX", "NAME OF ELECTED CANDIDATES", "CITY / MUNICIPALITY", "PROVINCE",
                "PARTY AFFILIATION", "POSITION /", "DISTRICT", "REGION", "POSITION", "PROVINCE / CITY",
                "POSITION / DISTRICT"}


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()

def _is_region(s):
    return s in {"ARMM", "CAR", "CARAGA", "NCR"} or s.startswith("NCR -") or s in NUM_REGIONS

def _is_district(s):
    return bool(re.fullmatch(r"(\d+(ST|ND|RD|TH)|LONE|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|"
                             r"SEVENTH|EIGHTH|NINTH) DISTRICT", s))

def _clean_lines(doc):
    for p in range(doc.page_count):
        for ln in doc[p].get_text().split("\n"):
            s = _norm(ln)
            if s and not s.startswith(_JUNK_PREFIX) and s not in _JUNK_LABELS:
                yield s


def parse_citymun(year):
    """Every elected mayor / vice-mayor / councilor in the year's citymun PDF."""
    import fitz
    doc = fitz.open(local_path(year, "citymun"))
    region = province = city = position = district = None
    buf, rows = [], []
    for s in _clean_lines(doc):
        if _is_region(s):
            if buf:
                province = buf[-1]
            if s.startswith("NCR"):
                province, region = (s if s != "NCR" else province), "NCR"
            else:
                region = s
            buf = []
        elif s in CITYMUN_POS:
            if buf:
                city = buf[-1]
            position, district, buf = s, None, []
        elif _is_district(s):
            district, buf = s, []
        elif s in ("M", "F"):
            party = buf[-1] if buf else ""
            rest = buf[:-1]
            if rest and re.fullmatch(r"\d+\.", rest[-1]):
                rest = rest[:-1]
            i = next((k for k, x in enumerate(rest) if "," in x), None)
            if i is not None:
                rows.append({"year": year, "region": region, "province": province, "city": city,
                             "position": position, "district": district or "",
                             "name": " ".join(rest[i:]), "party": party, "sex": s})
            buf = []
        else:
            buf.append(s)
    doc.close()
    return rows


PROV_POS = {"PROVINCIAL GOVERNOR", "PROVINCIAL VICE-GOVERNOR", "PROVINCIAL BOARD MEMBER"}


def _region_fix(s, province):
    """NCR is written as its district ('NCR - FOURTH DISTRICT'), which is the province-level
    unit; keep the district as the province and file it under region NCR."""
    if s.startswith("NCR"):
        return (s if s != "NCR" else province), "NCR"
    return province, s


def parse_provincial(year):
    """Governors, vice-governors and board members. Region sits in the page header (before the
    province); the province precedes the first position; a board member's district trails him
    as a bare rank number, which is skipped."""
    import fitz
    doc = fitz.open(local_path(year, "provincial"))
    region = province = position = district = None
    buf, rows = [], []
    for s in _clean_lines(doc):
        if _is_region(s):
            province, region = _region_fix(s, province); buf = []
        elif s in PROV_POS:
            if buf:
                province = buf[-1]
            position, district, buf = s, None, []
        elif _is_district(s):
            district, buf = s, []
        elif re.fullmatch(r"\d+", s):
            continue
        elif s in ("M", "F"):
            party = buf[-1] if buf else ""
            i = next((k for k, x in enumerate(buf[:-1]) if "," in x), None)
            if i is not None:
                rows.append({"year": year, "region": region, "province": province, "city": "",
                             "position": position, "district": district or "",
                             "name": " ".join(buf[:-1][i:]), "party": party, "sex": s})
            buf = []
        else:
            buf.append(s)
    doc.close()
    return rows


def parse_house(year):
    """Members of the House of Representatives. One per legislative district; the district label
    trails the candidate (ignored - the province/city is what the dataset keys on)."""
    import fitz
    doc = fitz.open(local_path(year, "house"))
    region = province = None
    buf, rows = [], []
    for s in _clean_lines(doc):
        if _is_region(s):
            province, region = _region_fix(s, province); buf = []
        elif _is_district(s):
            buf = []
        elif s in ("M", "F"):
            party = buf[-1] if buf else ""
            rest = buf[:-1]
            i = next((k for k, x in enumerate(rest) if "," in x), None)
            if i is not None:
                if i > 0:
                    province = rest[i - 1]
                rows.append({"year": year, "region": region, "province": province, "city": "",
                             "position": "MEMBER, HOUSE OF REPRESENTATIVES", "district": "",
                             "name": " ".join(rest[i:]), "party": party, "sex": s})
            buf = []
        else:
            buf.append(s)
    doc.close()
    return rows


def parse_year(year):
    """All elected candidates in one cycle, across the three category PDFs."""
    return parse_citymun(year) + parse_provincial(year) + parse_house(year)


# ----------------------------------------------------------------- normalise to schema
POSITION_MAP = {
    "MAYOR": "MAYOR", "VICE-MAYOR": "VICE MAYOR", "COUNCILOR": "COUNCILOR",
    "PROVINCIAL GOVERNOR": "GOVERNOR", "PROVINCIAL VICE-GOVERNOR": "VICE GOVERNOR",
    "PROVINCIAL BOARD MEMBER": "PROVINCIAL BOARD MEMBER",
    "MEMBER, HOUSE OF REPRESENTATIVES": "MEMBER, HOUSE OF REPRESENTATIVES",
}
# COMELEC province label (parenthetical stripped) -> our canonical province. Renamed provinces,
# the NCR hyphen, and independent cities that appear as a House "province" filed to their parent.
PROVINCE_MAP = {
    "TAWI-TAWI": "TAWI TAWI", "COMPOSTELA VALLEY": "DAVAO DE ORO", "DAVAO": "DAVAO DEL NORTE",
    "NCR - FIRST DISTRICT": "NCR FIRST DISTRICT", "NCR - SECOND DISTRICT": "NCR SECOND DISTRICT",
    "NCR - THIRD DISTRICT": "NCR THIRD DISTRICT", "NCR - FOURTH DISTRICT": "NCR FOURTH DISTRICT",
    "CEBU CITY": "CEBU", "DAVAO CITY": "DAVAO DEL SUR", "ILOILO CITY": "ILOILO",
    "BACOLOD CITY": "NEGROS OCCIDENTAL", "BAGUIO CITY": "BENGUET",
    "CAGAYAN DE ORO CITY": "MISAMIS ORIENTAL", "ZAMBOANGA CITY": "ZAMBOANGA DEL SUR",
    "CITY OF MANILA": "NCR FIRST DISTRICT", "CITY OF MAKATI": "NCR SECOND DISTRICT",
    "CITY OF PASIG": "NCR SECOND DISTRICT", "CITY OF MARIKINA": "NCR SECOND DISTRICT",
    "QUEZON CITY": "NCR SECOND DISTRICT", "SAN JUAN": "NCR SECOND DISTRICT",
    "CITY OF MANDALUYONG": "NCR SECOND DISTRICT", "KALOOCAN CITY": "NCR THIRD DISTRICT",
    "MALABON CITY - NAVOTAS": "NCR THIRD DISTRICT", "CITY OF VALENZUELA": "NCR THIRD DISTRICT",
    "PASAY CITY": "NCR FOURTH DISTRICT", "CITY OF PARAÑAQUE": "NCR FOURTH DISTRICT",
    "CITY OF LAS PIÑAS": "NCR FOURTH DISTRICT", "CITY OF MUNTINLUPA": "NCR FOURTH DISTRICT",
    "TAGUIG-PATEROS": "NCR FOURTH DISTRICT", "CITY OF ANTIPOLO": "RIZAL",
}


def _strip_paren(s):
    return re.sub(r"\s*\(.*?\)", "", str(s)).strip()


def _clean_prov(p):
    p = _strip_paren(p)
    return PROVINCE_MAP.get(p, p)


def _split_name(full):
    """'SURNAME, GIVEN MIDDLE' -> (last, first, middle). The middle name (a maternal surname or
    an initial) is the last token; everything between the comma and it is the given name."""
    if "," not in full:
        return full.strip(), "", ""
    last, rest = full.split(",", 1)
    toks = rest.split()
    if not toks:
        return last.strip(), "", ""
    if len(toks) == 1:
        return last.strip(), toks[0], ""
    return last.strip(), " ".join(toks[:-1]), toks[-1]


def to_winners_df(year):
    """The cycle's winners in the published NLE_Winners schema, with a Sex column."""
    import pandas as pd
    rows = []
    for r in parse_year(year):
        last, first, mid = _split_name(r["name"])
        rows.append({
            "Last Name": last, "First Name": first, "Middle Name": mid, "Title": "",
            "Full Name": r["name"], "Position": POSITION_MAP[r["position"]], "Party": r["party"],
            "Year": year, "Province": _clean_prov(r["province"]),
            "City": _strip_paren(r["city"]) if r["city"] else "", "Region": "", "Sex": r["sex"],
        })
    return pd.DataFrame(rows)


def build(year):
    """Write the cycle's winners to data/processed/listelected_{year}.csv for the merge step."""
    out = RAW.parents[1] / "processed" / f"listelected_{year}.csv"
    df = to_winners_df(year)
    df.to_csv(out, index=False)
    print(f"wrote {out} ({len(df):,} rows)")
    return out


# ----------------------------------------------------------------- sex backfill (all cycles)
# For 2004-2022 the winners are already in the dataset; only their SEX is missing. The layout
# drifts year to year (M/F vs MALE/FEMALE; party before or after sex; COUNCILOR vs "MEMBER,
# SANGGUNIANG BAYAN"), but SEX still ends each candidate and the name is the nearest preceding
# comma line that isn't a position - so name + sex + position extract without province or party.
SEX_TOK = {"M": "M", "F": "F", "MALE": "M", "FEMALE": "F"}
_POS_PATTERNS = [
    (r"VICE[ -]?MAYOR", "VICE MAYOR"), (r"\bMAYOR\b", "MAYOR"),
    (r"SANGGUNIANG (BAYAN|PANLUNGSOD)|\bCOUNCILOR\b", "COUNCILOR"),
    (r"VICE[ -]?GOVERNOR", "VICE GOVERNOR"), (r"\bGOVERNOR\b", "GOVERNOR"),
    (r"SANGGUNIANG PANLALAWIGAN|BOARD MEMBER", "PROVINCIAL BOARD MEMBER"),
    (r"HOUSE OF REPRESENTATIVES", "MEMBER, HOUSE OF REPRESENTATIVES"),
]
_JUNK_PREFIX_G = ("REPUBLIC", "COMMISSION", "INTRAMUROS", "RECORDS", "LIST OF", "PAGE ", "NOTICE",
                  "ALL AUTHORIZED", "INCLUDING", "CONFORMITY", "PRIVACY", "ACCOUNT", "AND ITS",
                  "SIMILARLY", "MAY ")
_JUNK_LABELS_G = {"SEX", "NAME OF ELECTED CANDIDATES", "PARTY AFFILIATION", "PARTY AFILLIATION",
                  "CITY / MUNICIPALITY", "POSITION / DISTRICT", "ELECTIVE POSITION", "DISTRICT",
                  "PROVINCE", "REGION", "PROVINCE / CITY", "CITY/MUNICIPALITY"}


def _match_pos(s):
    for pat, canon in _POS_PATTERNS:
        if re.search(pat, s):
            return canon
    return None


def parse_sex(year):
    """(year, canonical position, surname, given-first-token, M/F) for every winner in a cycle -
    layout-agnostic, used only to backfill Sex onto rows we already have."""
    import fitz
    out = []
    for cat in ("citymun", "provincial", "house"):
        path = local_path(year, cat)
        if not path.exists():
            continue
        doc = fitz.open(path)
        position, buf = None, []
        for p in range(doc.page_count):
            for ln in doc[p].get_text().split("\n"):
                s = _norm(ln)
                if not s:
                    continue
                u = s.upper()
                if u.startswith(_JUNK_PREFIX_G) or u in _JUNK_LABELS_G or ":" in s:
                    continue
                if u in SEX_TOK:
                    nm = next((x for x in reversed(buf) if "," in x and not _match_pos(x)), None)
                    if nm and position:
                        last, rest = nm.split(",", 1)
                        toks = _norm(rest).split()
                        if last.strip() and toks:
                            out.append((year, position, last.strip().upper(), toks[0].upper(), SEX_TOK[u]))
                    buf = []
                elif _match_pos(s) and ("," not in s or u.startswith("MEMBER,")):
                    position, buf = _match_pos(s), []
                else:
                    buf.append(s)
        doc.close()
    return out


def build_sex_lookup(years=(2004, 2007, 2010, 2013, 2016, 2019, 2022)):
    """Two lookups the merge step fills Sex from: an exact (Year, Position, surname, given) map
    where it is unambiguous, and a first-name -> Sex map for names that are gender-consistent
    (>= 99% one sex) - which recovers spelling mismatches between the PDF and our rows."""
    import csv
    import collections
    key_sex = collections.defaultdict(set)
    given_sex = collections.defaultdict(collections.Counter)
    for y in years:
        for (yr, pos, last, given, sex) in parse_sex(y):
            key_sex[(yr, pos, last, given)].add(sex)
            given_sex[given][sex] += 1
    proc = RAW.parents[1] / "processed"
    with (proc / "sex_by_key.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Year", "Position", "Last", "Given", "Sex"])
        for (yr, pos, last, given), sx in key_sex.items():
            if len(sx) == 1:
                w.writerow([yr, pos, last, given, next(iter(sx))])
    with (proc / "sex_by_given.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Given", "Sex"])
        for g, c in given_sex.items():
            tot = sum(c.values())
            top, n = c.most_common(1)[0]
            if tot >= 5 and n / tot >= 0.99:
                w.writerow([g, top])
    print("wrote sex_by_key.csv + sex_by_given.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dump", metavar="YEAR_CAT")
    ap.add_argument("--build", type=int, metavar="YEAR", help="write listelected_<year>.csv")
    ap.add_argument("--sex-lookup", action="store_true", help="write the 2004-2022 Sex lookups")
    args = ap.parse_args()
    if args.download:
        download(force=args.force)
    if args.dump:
        dump(args.dump)
    if args.build:
        build(args.build)
    if args.sex_lookup:
        build_sex_lookup()
