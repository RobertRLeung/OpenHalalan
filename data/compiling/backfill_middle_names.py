"""
Backfill missing middle names for the 2016-2025 cycles.

Those cycles are built from ballot feeds (GMA / ABS-CBN / COMELEC vote counts) that carry no
middle name, so ~87% of their winners have a blank Middle Name. This fills them from
authoritative winners-only sources, keyed to the SAME election wherever possible:

  * COMELEC's official List of Elected Candidates (`data/raw_data/comelec_lec/`, 2016/19/22)
    - names are "SURNAME, FIRST MIDDLE", ~100% carry the middle (a maternal surname).
  * the political-dynasty v8.5 source file (2016/19/22), province-level.
  * the winners dataset's own already-populated middle names (self-match).

Matching is SAME-YEAR first (a winner and their LEC twin are the same person, so a
province+city+position+surname+given key is safe). 2025 has no LEC/v8.5 yet, so it falls back
to a CROSS-YEAR self-match (the person's own earlier record) which is lower-confidence
(~80%, names recur across towns and generations) and is labelled as such.

Every filled cell records where it came from, in a new `Middle Name Source` column on the
winners dataset and in `data/audit/middle_name_backfill.csv`. Only BLANK middles are filled;
existing values are never overwritten.

    python data/compiling/backfill_middle_names.py --report      # coverage + precision, no writes
    python data/compiling/backfill_middle_names.py --apply       # write winners + vote counts + audit
"""
import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "scraping"))

from normalize import canonical_province, canonical_city  # noqa: E402
import scrape_listelected as SL  # noqa: E402
import fitz  # noqa: E402

WINNERS = ROOT / "output" / "NLE_Winners_2004-2025.csv"
VOTE_COUNTS = ROOT / "output" / "NLE_Vote_Counts_2010-2025.csv.gz"
V85 = ROOT / "source" / "political_dynasty_v8.5.csv"
AUDIT = ROOT / "audit" / "middle_name_backfill.csv"

_V85 = None   # the political-dynasty v8.5 source frame, loaded once in report()/apply_winners()

CITY_POS = {"MAYOR", "VICE MAYOR", "COUNCILOR"}
GOV_POS = {"GOVERNOR", "VICE GOVERNOR"}          # exactly one per province -> province key is safe
LEC_YEARS = (2016, 2019, 2022)

# --------------------------------------------------------------------------- normalisation
def fold(s):
    if s is None or (isinstance(s, float)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()

from functools import lru_cache

@lru_cache(maxsize=None)
def cprov(x):
    try:
        return fold(canonical_province(x))
    except Exception:
        return fold(x)

@lru_cache(maxsize=None)
def ccity(x):
    try:
        return fold(canonical_city(x))
    except Exception:
        return fold(x)

def given(s):
    t = fold(s).split()
    return t[0] if t else ""

def has_mid(x):
    return isinstance(x, str) and len(str(x).replace(".", "").strip()) > 1

def mid_compat(a, b):
    """Two middles are compatible if equal, or one is the other's initial (first token)."""
    a, b = fold(a).split(), fold(b).split()
    if not a or not b:
        return None
    a, b = a[0], b[0]
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return False

# --------------------------------------------------------------------------- LEC extraction
NUM_REGIONS = {"I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII"}
def _is_region(s):
    return s in {"ARMM","BARMM","CAR","CARAGA","NCR"} or s.startswith("NCR ") or s in NUM_REGIONS

_POS_PATTERNS = [
    (r"^VICE[ -]?MAYOR$", "VICE MAYOR"),
    (r"^MAYOR$", "MAYOR"),
    (r"^(MEMBER, )?SANGGUNIANG (BAYAN|PANLUNGSOD)$|^COUNCILOR$", "COUNCILOR"),
    (r"^VICE[ -]?GOVERNOR$|^PROVINCIAL VICE-GOVERNOR$", "VICE GOVERNOR"),
    (r"^(PROVINCIAL )?GOVERNOR$", "GOVERNOR"),
    (r"^(MEMBER, )?SANGGUNIANG PANLALAWIGAN$|^PROVINCIAL BOARD MEMBER$|^BOARD MEMBER$", "PROVINCIAL BOARD MEMBER"),
    (r"HOUSE OF REPRESENTATIVES", "MEMBER, HOUSE OF REPRESENTATIVES"),
]
def _match_pos(s):
    for pat, canon in _POS_PATTERNS:
        if re.search(pat, s):
            return canon
    return None

_JUNK_PREFIX = ("Republic of the","COMMISSION ON","Intramuros","Records and","LIST OF ELEC",
                "May ","Page ","Notice","All authorized","including other","conformity",
                "Privacy","account","and its Impl","similarly bound","NAME OF ELEC")
_JUNK_LABELS = {"SEX","PARTY","AFFILIATION","PARTY AFFILIATION","PARTY AFILLIATION","DISTRICT",
                "ELECTIVE POSITION","REGION / PROVINCE /","CITY / MUNICIPALITY /","POSITION / DISTRICT",
                "NAME OF ELECTED CANDIDATES","REGION","PROVINCE","POSITION","BARMM DISTRICT",
                "PROVINCE / CITY","CITY/MUNICIPALITY","CITY / MUNICIPALITY","POSITION /","POSITION/DISTRICT"}
def _clean_lines(doc):
    # Every real datum in the LEC (names, provinces, cities, positions, party codes) is printed
    # in UPPERCASE; only the page header/footer boilerplate carries lowercase letters. Dropping
    # any line with a lowercase letter removes the wrapped "Notice:" footer prose that would
    # otherwise be parsed as comma-bearing candidate names.
    for p in range(doc.page_count):
        for ln in doc[p].get_text().split("\n"):
            s = re.sub(r"\s+", " ", ln).strip()
            if s and not re.search(r"[a-z]", s) and s not in _JUNK_LABELS:
                yield s

def _split_name(full):
    if "," not in full:
        return None
    last, rest = full.split(",", 1)
    toks = rest.split()
    if not last.strip() or not toks:
        return None
    if len(toks) == 1:
        return last.strip(), toks[0], ""
    return last.strip(), " ".join(toks[:-1]), toks[-1]

_HDR = re.compile(r"^PROVINCE/CITY/MUN\.?\s*:\s*(.+)$")          # 2022 layout: "CITY, PROVINCE"
_REGION_PFX = re.compile(r"^REGION\s*:\s*(.+)$")                 # 2016 layout
_PROV_PFX = re.compile(r"^PROVINCE\s*:\s*(.+)$")                 # 2016 layout
_SEX = {"M", "F", "MALE", "FEMALE"}
_DISTRICT = re.compile(r"^(\d+(ST|ND|RD|TH)|LONE|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|"
                       r"SEVENTH|EIGHTH|NINTH|TENTH) DISTRICT$")

def _extract(year, cat):
    """(province, city, position, last, first, middle) for every winner in one LEC PDF.

    Each candidate is a record unit: NAME -> [rank '1.'] -> exactly two tokens that are the
    party and the sex, in either order (2016 lists party first, 2019/2022 sex first). Consuming
    the pair as a unit keeps party codes out of the locality buffer regardless of the layout.
    A citymun row's city is the bare line right before its MAYOR; province comes from the
    explicit REGION:/PROVINCE: prefixes (2016), the header (2022), or the stacked bare lines
    (2019)."""
    doc = fitz.open(SL.local_path(year, cat))
    province = city = position = None
    loc_buf, rows = [], []
    pending = None          # a name awaiting its (party, sex) pair
    pend_ct = 0
    for s in _clean_lines(doc):
        if pending is not None:
            if re.fullmatch(r"\d+\.?", s):
                continue                    # rank marker inside the record
            if pend_ct < 2 and _match_pos(s) is None and "," not in s \
               and not _REGION_PFX.match(s) and not _PROV_PFX.match(s) \
               and not _HDR.match(s) and not _is_region(s):
                pend_ct += 1                # one of the (party, sex) pair, either order
                if pend_ct >= 2:
                    pending = None
                continue
            pending = None                  # record ended early (blank party etc.)
        m = _REGION_PFX.match(s)
        if m:
            province = None; loc_buf = []; continue
        m = _PROV_PFX.match(s)
        if m:
            province = m.group(1).strip(); loc_buf = []; continue
        m = _HDR.match(s)
        if m:
            parts = [x.strip() for x in m.group(1).split(",")]
            city = parts[0]
            if len(parts) > 1:
                province = parts[1]
            loc_buf = []; continue
        if s.startswith("PROVINCE/CITY/MUN"):
            loc_buf = []; continue
        if _is_region(s):
            loc_buf = []; continue
        if _DISTRICT.match(s):
            continue                        # district labels are not localities
        pos = _match_pos(s)
        if pos and ("," not in s or s.upper().startswith("MEMBER,")):
            if pos == "MAYOR" and loc_buf:              # city is the bare line before MAYOR
                city = loc_buf[-1]
                if len(loc_buf) >= 2:
                    province = loc_buf[-2]              # 2019 stacked province (province changed)
            elif cat != "citymun" and loc_buf:
                province = loc_buf[-1]
            loc_buf = []; position = pos; continue
        if "," in s:
            nm = _split_name(s)
            if nm and position:
                rows.append((province, city, position, nm[0], nm[1], nm[2]))
            pending = s; pend_ct = 0; continue
        loc_buf.append(s)
    doc.close()
    return rows

def lec_records(year):
    recs = []
    for cat in ("citymun", "provincial", "house"):
        if SL.local_path(year, cat).exists():
            recs += _extract(year, cat)
    return recs

# --------------------------------------------------------------------------- source tuples
def lec_tuples(year):
    """(cprov, ccity, position, surname, given, middle) from the LEC PDFs for one cycle
    (plus the old parser for 2016, whose province is cleaner)."""
    for prov, city, pos, last, first, mid in lec_records(year):
        if has_mid(mid):
            yield cprov(prov), ccity(city), pos, fold(last), given(first), mid.strip()
    if year == 2016:
        for _, x in SL.to_winners_df(2016).iterrows():
            if has_mid(x["Middle Name"]):
                yield cprov(x["Province"]), ccity(x["City"]), x["Position"], fold(x["Last Name"]), given(x["First Name"]), x["Middle Name"].strip()

def v85_tuples(year):
    """v8.5 rows for one cycle. It has no city, so it only feeds the province-office key."""
    vy = _V85
    vy = vy[vy["Year"] == str(year)]
    for _, x in vy.iterrows():
        if has_mid(x["Middle Name"]):
            yield cprov(x["Province"]), "", x["Position"], fold(x["Last Name"]), given(x["First Name"]), x["Middle Name"].strip()

def crossyear_tuples(winners):
    """Every winner source across all cycles, for the 2025 self-match (a person's own earlier
    record). Exact-given only downstream, so no surname-only tier."""
    for y in LEC_YEARS:
        yield from lec_tuples(y)
    for _, x in _V85.iterrows():
        if has_mid(x["Middle Name"]):
            yield cprov(x["Province"]), ccity(x["City"]) if x.get("City") else "", x["Position"], fold(x["Last Name"]), given(x["First Name"]), x["Middle Name"].strip()
    for _, x in winners[winners["Year"] != "2025"].iterrows():
        if has_mid(x["Middle Name"]):
            yield cprov(x["Province"]), ccity(x["City"]), x["Position"], fold(x["Last Name"]), given(x["First Name"]), x["Middle Name"].strip()

def build_index(tuples):
    """Two conflict-suppressed lookups. City offices key on (city, surname, given) WITHOUT
    province: city extraction is reliable across all three PDF layouts while province is not,
    and conflict-suppression drops the rare same-name-town collision (costing recall, never
    precision). Governor / vice-governor (one per province) key on (province, position,
    surname, given), which v8.5 supplies cleanly."""
    city_k = defaultdict(set)
    citylast_k = defaultdict(set)
    gov_k = defaultdict(set)
    for prov, city, pos, last, gv, mid in tuples:
        if pos in CITY_POS and city:
            city_k[(city, last, gv)].add(mid)
            citylast_k[(city, last)].add(mid)
        elif pos in GOV_POS:
            gov_k[(prov, pos, last, gv)].add(mid)
    uniq = lambda d: {k: next(iter(v)) for k, v in d.items() if len(v) == 1}
    return uniq(city_k), uniq(citylast_k), uniq(gov_k)

def lookup(idx, prov, city, pos, last, gv, allow_surname_only=False):
    """allow_surname_only enables the (city, surname) tier, which tolerates given-name spelling
    drift (nicknames) but is safe ONLY within the same election, where a surname unique to a
    town's winners is one person. It is off for the cross-year 2025 self-match."""
    city_k, citylast_k, gov_k = idx
    if pos in CITY_POS:
        return city_k.get((city, last, gv)) or (citylast_k.get((city, last)) if allow_surname_only else None)
    if pos in GOV_POS:
        return gov_k.get((prov, pos, last, gv))
    return None

# --------------------------------------------------------------------------- driver
def resolve_for_year(winners, year):
    """Return {row_index: (middle, source_label)} for blank rows of one cycle.

    2016/19/22: same-year LEC first (label comelec_lec), then v8.5 (label v8.5); both allow the
    safe surname-only tier. 2025: cross-year self-match, exact given only (label self-prior)."""
    if year == 2025:
        stages = [(build_index(crossyear_tuples(winners)), "self-prior", False)]
    else:
        stages = [(build_index(lec_tuples(year)), "comelec_lec", True),
                  (build_index(v85_tuples(year)), "v8.5", True)]
    out = {}
    sub = winners[(winners["Year"] == str(year)) & (~winners["Middle Name"].apply(has_mid))]
    for i, r in sub.iterrows():
        for idx, label, surname_ok in stages:
            m = lookup(idx, cprov(r["Province"]), ccity(r["City"]), r["Position"],
                       fold(r["Last Name"]), given(r["First Name"]), allow_surname_only=surname_ok)
            if m:
                out[i] = (m, label)
                break
    return out

def report():
    global _V85
    _V85 = pd.read_csv(V85, dtype=str).fillna("")
    W = pd.read_csv(WINNERS, dtype=str).fillna("")
    print("Backfill coverage (blank middle names filled), by cycle:")
    for year in (2016, 2019, 2022, 2025):
        blank = ((W["Year"] == str(year)) & (~W["Middle Name"].apply(has_mid))).sum()
        got = resolve_for_year(W, year)
        print(f"  {year}: {len(got):>5}/{blank:<5} blanks filled ({100*len(got)/max(blank,1):.0f}%)")


def apply_winners():
    """Fill blank Middle Name on the winners dataset, add a Middle Name Source column, and
    regenerate Full Name for filled rows. Returns (winners_df, audit_rows)."""
    from normalize import canonical_full_name
    global _V85
    _V85 = pd.read_csv(V85, dtype=str).fillna("")
    W = pd.read_csv(WINNERS, dtype=str).fillna("")
    src = pd.Series([""] * len(W), index=W.index)
    src[W["Middle Name"].apply(has_mid)] = "original"
    audit = []
    for year in (2016, 2019, 2022, 2025):
        for i, (mid, label) in resolve_for_year(W, year).items():
            r = W.loc[i]
            W.at[i, "Middle Name"] = mid
            W.at[i, "Full Name"] = canonical_full_name(r["Last Name"], r["First Name"], mid)
            src[i] = label
            audit.append({"dataset": "winners", "year": year, "province": r["Province"],
                          "city": r["City"], "position": r["Position"], "last_name": r["Last Name"],
                          "first_name": r["First Name"], "middle_filled": mid, "source": label})
    cols = list(W.columns)
    W["Middle Name Source"] = src
    W = W[cols[:cols.index("Middle Name") + 1] + ["Middle Name Source"] + cols[cols.index("Middle Name") + 1:]]
    return W, audit


def build_person_index(winners_backfilled):
    """Cross-year (city, surname, given) -> middle, conflict-suppressed over every winner source
    (backfilled winners of all years + LEC + v8.5). Used to carry middles into the vote-counts
    file, including a few losers who won in another cycle. Exact given only (no surname-only) to
    stay safe across years."""
    city_k = defaultdict(set)
    for _, x in winners_backfilled.iterrows():
        if has_mid(x["Middle Name"]) and x["Position"] in CITY_POS and str(x["City"]).strip():
            city_k[(ccity(x["City"]), fold(x["Last Name"]), given(x["First Name"]))].add(x["Middle Name"].strip())
    for y in LEC_YEARS:
        for prov, city, pos, last, first, mid in lec_records(y):
            if has_mid(mid) and pos in CITY_POS and city:
                city_k[(ccity(city), fold(last), given(first))].add(mid.strip())
    return {k: next(iter(v)) for k, v in city_k.items() if len(v) == 1}


def apply_vote_counts(winners_backfilled, audit):
    """Fill blank middle_name on the vote-counts file for 2016-2025, regenerate candidate_name,
    and append to the audit.

    Two passes. First, WINNER rows are matched to their own backfilled winners record for the
    same cycle at (year, city, position, surname, given) - the same person, so the vote-counts
    winners end up identical to the winners dataset. Then any remaining blank (mostly losers) is
    tried against the cross-year person index, which carries a middle for anyone who won in some
    cycle."""
    from normalize import canonical_full_name
    # same-year winner map from the backfilled winners dataset
    same = defaultdict(set)
    for _, x in winners_backfilled.iterrows():
        if has_mid(x["Middle Name"]) and x["Position"] in CITY_POS and str(x["City"]).strip():
            same[(x["Year"], ccity(x["City"]), x["Position"], fold(x["Last Name"]), given(x["First Name"]))].add(x["Middle Name"].strip())
    same = {k: next(iter(v)) for k, v in same.items() if len(v) == 1}
    cross = build_person_index(winners_backfilled)

    d = pd.read_csv(VOTE_COUNTS, dtype=str).fillna("")
    # Mark the actual winner of each race (max votes) so the same-year winner map is only applied
    # to winners - never to a losing namesake (often a relative) who shares surname+given.
    d["_v"] = pd.to_numeric(d["votes"], errors="coerce").fillna(-1)
    race = ["year", "region", "province", "city", "district", "position"]
    is_winner = d.index.isin(d.loc[d.groupby(race)["_v"].idxmax()].index)
    target = (d["year"].isin([str(y) for y in (2016, 2019, 2022, 2025)])
              & d["position"].isin(CITY_POS)
              & (~d["middle_name"].apply(has_mid)))
    tgt = d[target]
    win = pd.Series(is_winner, index=d.index)[target].tolist()
    yr = tgt["year"].tolist(); ct = [ccity(c) for c in tgt["city"]]
    pos = tgt["position"].tolist(); ln = [fold(x) for x in tgt["last_name"]]
    gv = [given(x) for x in tgt["first_name"]]
    mids, srcs = [], []
    for w, y, c, p, l, g in zip(win, yr, ct, pos, ln, gv):
        m = same.get((y, c, p, l, g)) if w else None
        if m:
            mids.append(m); srcs.append("winner-match")
        else:
            m2 = cross.get((c, l, g))
            mids.append(m2); srcs.append("person-index" if m2 else None)
    mids = pd.Series(mids, index=tgt.index)
    hit = mids.notna()
    idxs = tgt.index[hit]
    d.loc[idxs, "middle_name"] = mids[hit]
    d.loc[idxs, "candidate_name"] = [
        canonical_full_name(l, f, m) for l, f, m in
        zip(d.loc[idxs, "last_name"], d.loc[idxs, "first_name"], mids[hit])
    ]
    srcmap = dict(zip(tgt.index, srcs))
    for i in idxs:
        audit.append({"dataset": "vote_counts", "year": d.at[i, "year"], "province": d.at[i, "province"],
                      "city": d.at[i, "city"], "position": d.at[i, "position"], "last_name": d.at[i, "last_name"],
                      "first_name": d.at[i, "first_name"], "middle_filled": d.at[i, "middle_name"], "source": srcmap[i]})
    winner_n = sum(1 for i in idxs if srcmap[i] == "winner-match")
    print(f"  vote counts: filled {len(idxs):,} blank middle names "
          f"({winner_n:,} winner rows, {len(idxs)-winner_n:,} others via cross-cycle self-match)")
    return d.drop(columns=["_v"])


def apply():
    W, audit = apply_winners()
    nfill = sum(1 for a in audit if a["dataset"] == "winners")
    print(f"Winners: filled {nfill:,} blank middle names")
    for year in (2016, 2019, 2022, 2025):
        n = sum(1 for a in audit if a["dataset"] == "winners" and a["year"] == year)
        print(f"    {year}: {n:,}")
    D = apply_vote_counts(W, audit)
    W.to_csv(WINNERS, index=False)
    D.to_csv(VOTE_COUNTS, index=False, compression="gzip")
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(audit).to_csv(AUDIT, index=False)
    print(f"Wrote {WINNERS.name}, {VOTE_COUNTS.name}, and {AUDIT.name} ({len(audit):,} audit rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.report:
        report()
    if args.apply:
        apply()
