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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dump", metavar="YEAR_CAT")
    args = ap.parse_args()
    if args.download:
        download(force=args.force)
    if args.dump:
        dump(args.dump)
