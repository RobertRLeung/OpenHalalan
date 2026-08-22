"""
Consolidate the per-municipality COMELEC scrapes into one published vote-counts dataset.

  data/raw_data/{2022,2025}/**/*.csv  ->  data/output/NLE_Vote_Counts_2007-2025.csv.gz

One row per candidate per office per locality: every candidate, winners and losers alike.
Place names are canonicalised so a locality keeps one key across cycles, and the office is
split out of COMELEC's location-laden `position` string.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import re

import pandas as pd

from config import OUTPUT, PROCESSED, VOTE_COUNT_YEARS, VOTE_COUNTS_CSV, raw_dir
from normalize import (
    NON_GEOGRAPHIC,
    canonical_city,
    canonical_full_name,
    canonical_party,
    canonical_region,
    clean_reported_name,
    drop_duplicate_rows,
    resolve_province,
    standardize_name,
)

# COMELEC embeds the locality in the office string, and the two cycles do it DIFFERENTLY:
#
#   2025: "MAYOR of ILOCOS NORTE - ADAMS"          <- office, then " of ", then the place
#         "SENATOR of PHILIPPINES"
#   2022: "MAYOR COTABATO - ALAMADA"               <- no separator at all
#         "PROVINCIAL GOVERNOR COTABATO"
#         "MEMBER, SANGGUNIANG BAYAN COTABATO - ALAMADA - LONE DIST"
#
# 2022 also uses the Filipino names for the local legislatures where 2025 uses the English
# ones. Both are mapped onto the same canonical office so the cycles are comparable.
#
# Ordered longest-prefix-first: "VICE-MAYOR" must be tested before "MAYOR", and
# "PROVINCIAL VICE-GOVERNOR" before "PROVINCIAL GOVERNOR".
OFFICE_PATTERNS = [
    # BARMM's regional parliament, elected for the first time in 2025. A real office, and
    # one the winners dataset does not carry (that covers the 7 national/local offices
    # only). Its districts use a REGDIST suffix.
    ("BARMM MEMBERS OF THE PARLIAMENT", "BARMM MEMBER OF PARLIAMENT"),
    # ARMM's regional government, elected until 2016. BARMM replaced ARMM in 2019, and its
    # parliament (above) is the successor to the Regional Legislative Assembly. Kept
    # distinct rather than merged: they are different institutions under different laws.
    ("REGIONAL VICE-GOVERNOR", "ARMM REGIONAL VICE GOVERNOR"),
    ("REGIONAL VICE GOVERNOR", "ARMM REGIONAL VICE GOVERNOR"),
    ("REGIONAL GOVERNOR", "ARMM REGIONAL GOVERNOR"),
    ("ASSEMBLYMAN", "ARMM ASSEMBLYMAN"),
    ("BARMM PARTY REPRESENTATIVES", "BARMM PARTY REPRESENTATIVE"),
    ("MEMBER, HOUSE OF REPRESENTATIVES", "MEMBER, HOUSE OF REPRESENTATIVES"),
    # ABS-CBN 2019 calls the office "Congressman". A handful of its contests omit the
    # detailed string entirely, so the scraper falls back to this bare position name -
    # those rows carry no district.
    ("CONGRESSMAN", "MEMBER, HOUSE OF REPRESENTATIVES"),
    ("MEMBER, SANGGUNIANG PANLALAWIGAN", "PROVINCIAL BOARD MEMBER"),
    ("PROVINCIAL BOARD MEMBER", "PROVINCIAL BOARD MEMBER"),
    ("MEMBER, SANGGUNIANG PANLUNGSOD", "COUNCILOR"),  # city council
    ("MEMBER, SANGGUNIANG BAYAN", "COUNCILOR"),  # municipal council
    # COMELEC's own typo, one G short, and it appears in exactly one contest in the whole
    # archive: Bangued, Abra, 2022 (17 rows). Spelled out rather than handled by a looser
    # pattern, because a looser pattern is how a real unknown office gets silently
    # swallowed - which is the thing this table exists to prevent.
    ("MEMBER, SANGUNIANG BAYAN", "COUNCILOR"),
    ("COUNCILOR", "COUNCILOR"),
    ("PROVINCIAL VICE-GOVERNOR", "VICE GOVERNOR"),
    ("PROVINCIAL VICE GOVERNOR", "VICE GOVERNOR"),
    ("VICE-GOVERNOR", "VICE GOVERNOR"),
    ("VICE GOVERNOR", "VICE GOVERNOR"),
    ("PROVINCIAL GOVERNOR", "GOVERNOR"),
    ("GOVERNOR", "GOVERNOR"),
    ("VICE-MAYOR", "VICE MAYOR"),
    ("VICE MAYOR", "VICE MAYOR"),
    ("MAYOR", "MAYOR"),
    ("VICE-PRESIDENT", "VICE PRESIDENT"),
    ("VICE PRESIDENT", "VICE PRESIDENT"),
    ("PRESIDENT", "PRESIDENT"),
    ("SENATOR", "SENATOR"),
    ("PARTY LIST", "PARTY LIST"),
]

# The district identifier, with the redundant suffix stripped.
#
# COMELEC writes "FIRST LEGDIST" / "THIRD PROVDIST" / "LONE DIST", but the suffix only
# restates the office (LEGDIST <-> house member, PROVDIST <-> provincial board, DIST <->
# councilor), so it carries no information. What matters is the identifier itself: it names
# the jurisdiction the votes are counted in.
#
# Usually an ordinal (LONE, FIRST, SECOND, ...) but NOT always: some councils have named
# districts (BABAK, KAPUTIAN and SAMAL in the Island Garden City of Samal; BACON in
# Sorsogon; EAST and WEST). Keep whatever the identifier is.
DISTRICT_RE = re.compile(r"([A-Z]+(?:\s+[A-Z]+)*?)\s+(?:LEGDIST|PROVDIST|REGDIST|DIST)\s*$")

# Races decided nationwide rather than by the locality reporting them. For these, `rank`
# is only the candidate's standing WITHIN that locality, not who won the seat.
NATIONAL_OFFICES = {"PRESIDENT", "VICE PRESIDENT", "SENATOR", "PARTY LIST"}

# Offices where the "candidate" is an ORGANISATION, not a person. The ballot lists them by
# number and name - "63 AMIN", "5 ABANG LINGKOD" - and they have no party, because they
# ARE the party.
#
# These must never go through the person-name parser: it comma-splits them into nonsense
# ("BAYAN MUNA" -> "MUNA, 81 BAYAN"), which is what an earlier build shipped for 405 of
# the 412 distinct party-list organisations, across 47.8% of the dataset.
NON_PERSON_OFFICES = {"PARTY LIST", "BARMM PARTY REPRESENTATIVE"}

_BALLOT_NUMBER = re.compile(r"^\s*\d+\s+")


def split_position(position):
    """
    Return (canonical position, district) from a source's location-laden position string.

    The canonical position uses the SAME vocabulary as the winners dataset's `Position`
    column, so the two datasets are directly joinable.

    Handles every source's format. Unrecognised offices return (None, None) rather than
    leaking the raw string, so the audit can count them.
    """
    if pd.isna(position):
        return None, None

    text = re.sub(r"\s+", " ", str(position).strip().upper())

    position_name = None
    for prefix, canonical in OFFICE_PATTERNS:
        if text.startswith(prefix):
            position_name = canonical
            text = text[len(prefix):]
            break

    if position_name is None:
        return None, None

    # Whatever follows the office is the locality; the district, if any, trails it.
    remainder = re.sub(r"^\s*(OF\s+)?", "", text).strip()
    match = DISTRICT_RE.search(remainder)

    return position_name, match.group(1).strip() if match else None


# 2013 does not come from a COMELEC scrape - it is reconstructed from Rappler's archived
# results (see data/scraping/scrape_2013_rappler.py). Its region/province/city arrive as URL
# slugs, so they are decoded to the SAME canonical strings the other cycles already use.
REGION_SLUG = {
    "armm": "BARMM", "car": "CORDILLERA ADMINISTRATIVE REGION", "caraga": "REGION XIII",
    "ncr": "NATIONAL CAPITAL REGION", "region-1": "REGION I", "region-2": "REGION II",
    "region-3": "REGION III", "region-4a": "REGION IV A", "region-4b": "REGION IV B",
    "region-5": "REGION V", "region-6": "REGION VI", "region-7": "REGION VII",
    "region-8": "REGION VIII", "region-9": "REGION IX", "region-10": "REGION X",
    "region-11": "REGION XI", "region-12": "REGION XII",
}
# Province slugs whose plain de-slugging is not the canonical name: NCR is filed under
# "metropolitan-manila" (resolve_province needs "METRO MANILA" to recover the district from
# the city), and Rappler names two provinces by their long form.
PROV_SLUG_FIX = {"metropolitan-manila": "METRO MANILA", "north-cotabato": "COTABATO",
                 "western-samar": "SAMAR"}


def load_2013():
    """Shape the 2013 Rappler archive into the same raw columns as a COMELEC scrape, so it
    flows through the identical normalisation. The office is rebuilt into the location-laden
    form split_position expects, carrying the House/board district that lives in `area`;
    rank and percentage are computed per race (Rappler published neither)."""
    src = PROCESSED / "rappler_2013.csv"
    if not src.exists():
        print("  (no rappler_2013.csv; skipping 2013)")
        return None
    d = pd.read_csv(src, dtype=str).fillna("")
    # Rappler's /2010/ result pages were only archived in 2016-2018, by which time the site
    # served 2013 content at those URLs (no presidential race on a 2010 presidential-year page;
    # values byte-match /2013/; province governors are the 2013 winners). They therefore
    # RECOVER 2013 municipalities that /2013/ never archived - Ilocos Sur, Cagayan, Antique.
    # Merge municipalities not already present; primary /2013/ wins any overlap.
    mirror = PROCESSED / "rappler_2013_mirror.csv"
    if mirror.exists():
        m = pd.read_csv(mirror, dtype=str).fillna("")
        have = set(zip(d["province"], d["city"]))
        m = m[[(p, c) not in have for p, c in zip(m["province"], m["city"])]]
        if len(m):
            d = pd.concat([d, m], ignore_index=True)
            print(f"  2013: +{m.groupby(['province','city']).ngroups} municipalities from the /2010/-URL 2013 mirror")
    unslug = lambda s: re.sub(r"[-_]+", " ", s).strip().upper()
    out = pd.DataFrame({
        "region": d["region"].map(lambda s: REGION_SLUG.get(s, "")),
        "province": d["province"].map(lambda s: PROV_SLUG_FIX.get(s, unslug(s))),
        "city": d["city"].map(unslug),
        "position": [f"{p} of {a}" if a else p for p, a in zip(d["position"], d["area"])],
        "candidate_name": d["candidate_name"],
        "party": d["party"],
        "votes": pd.to_numeric(d["votes"], errors="coerce").fillna(0).astype(int),
    })
    # A race is one office in one locality; the location-laden position string already keeps
    # House and multi-district board contests apart.
    race = ["province", "city", "position"]
    tot = out.groupby(race)["votes"].transform("sum")
    out["percentage"] = (100 * out["votes"] / tot.where(tot > 0)).round(2)
    out["rank"] = out.groupby(race)["votes"].rank(ascending=False, method="min").astype(int)
    out["year"] = 2013
    print(f"  2013: Rappler archive -> {len(out):,} rows")
    return out


def _load_ianmaps_2010():
    """The Ianmaps national tabulation: president/VP/senator per municipality, no party. Covers
    more municipalities than the COMELEC archive does for the national races."""
    src = PROCESSED / "national_2010.csv"
    if not src.exists():
        return None
    d = pd.read_csv(src, dtype=str).fillna("")
    # NCR is filed as "NATIONAL CAPITAL REGION [- METRO MANILA]"; resolve_province needs
    # "METRO MANILA" to recover the district from the city (cf. PROV_SLUG_FIX for 2013).
    province = d["province"].str.replace(r"(?i)^national capital region.*", "METRO MANILA", regex=True)
    return pd.DataFrame({
        "region": d["region"], "province": province, "city": d["city"],
        "position": [f"{p} of PHILIPPINES" for p in d["position"]],
        "candidate_name": d["candidate_name"].str.upper(),
        "party": "",
        "votes": pd.to_numeric(d["votes"], errors="coerce").fillna(0).astype(int),
    })


def _load_comelec_2010():
    """The archived COMELEC/Smartmatic per-municipality results (scrape_2010_comelec.py): every
    office - national AND local - with party. The `office` column is the raw location-laden label
    ("MAYOR of ABRA - BANGUED"), which split_position parses like any other feed."""
    src = PROCESSED / "comelec_2010.csv.gz"
    if not src.exists():
        return None
    c = pd.read_csv(src, dtype=str).fillna("")
    # region isn't on the page; carry it over from Ianmaps' province -> region.
    ian = pd.read_csv(PROCESSED / "national_2010.csv", dtype=str).fillna("") if (PROCESSED / "national_2010.csv").exists() else None
    p2r = {}
    if ian is not None:
        for prov, reg in zip(ian["province"], ian["region"]):
            p2r.setdefault(prov.upper(), reg)
    return pd.DataFrame({
        "region": [p2r.get(p.upper(), "") for p in c["province"]],
        "province": c["province"], "city": c["city"], "position": c["office"],
        "candidate_name": c["candidate_name"].str.upper(), "party": c["party"],
        "votes": pd.to_numeric(c["votes"], errors="coerce").fillna(0).astype(int),
    })


# Filipino surname particles a natural-order name keeps with the surname.
_PARTICLES = {"de", "dela", "delos", "del", "los", "las", "san", "sta", "sto", "santa", "santo"}
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


def _natural_to_comma(name):
    """Wikipedia writes "First Middle Last"; the pipeline expects COMELEC's "LAST, FIRST". Best
    effort - the surname is the last token, extended back over particles ("de los Santos")."""
    name = re.sub(r"\s+", " ", str(name)).strip()
    if "," in name or " " not in name:
        return name
    toks = name.split()
    given_suffix = toks.pop() if toks[-1].rstrip(".").upper() in _SUFFIXES else ""
    surname = [toks.pop()]
    while toks and toks[-1].lower() in _PARTICLES:
        surname.insert(0, toks.pop())
    given = " ".join(toks + ([given_suffix] if given_suffix else []))
    return f"{' '.join(surname)}, {given}".strip().strip(",")


def _load_wikipedia(year):
    """Executive races (governor/vice-governor/mayor/vice-mayor) from Wikipedia's per-province and
    per-city articles (scrape_wikipedia_local.py). The office is already canonical and the locality
    is a bare province or city; region is recovered later from the place. Drops within-file
    duplicates where a race appears in both an umbrella and a per-locality article."""
    src = PROCESSED / f"wikipedia_{year}.csv.gz"
    if not src.exists():
        return None
    w = pd.read_csv(src, dtype=str).fillna("")
    w["votes"] = pd.to_numeric(w["votes"], errors="coerce").fillna(0).astype(int)
    w = (w.sort_values("votes", ascending=False)
          .drop_duplicates(["province", "city", "position", "candidate_name"]))
    # Place names must be upper-case to key against every other feed.
    prov = w["province"].str.upper().str.strip()
    city = w["city"].str.upper().str.strip()
    # City articles carry no province; recover it from the town using the winners dataset as a
    # nationwide city -> province authority. Match on the canonical city so ñ and "City" suffix
    # spellings line up. A town name is unique enough that this is safe.
    city2prov = _city_to_province()
    prov = [p or city2prov.get(canonical_city(c), "") for p, c in zip(prov, city)]
    out = pd.DataFrame({
        "region": "", "province": prov, "city": city, "position": w["position"],
        "candidate_name": [_natural_to_comma(n).upper() for n in w["candidate_name"]],
        "party": w["party"], "votes": w["votes"],
    })
    # The same candidate can appear in both a province article and a city article with a slightly
    # different name (a nickname in one). Same race + same surname + same votes is the same person;
    # keep the fuller name. Genuinely tied rivals differ by surname, so they survive.
    out["_sur"] = out["candidate_name"].str.split(",").str[0]
    out = (out.assign(_len=out["candidate_name"].str.len())
              .sort_values("_len", ascending=False)
              .drop_duplicates(["province", "city", "position", "_sur", "votes"])
              .drop(columns=["_sur", "_len"]))
    return out


def _city_to_province():
    """CITY -> PROVINCE from the published winners dataset (its most common province per city)."""
    src = OUTPUT / "NLE_Winners_2004-2025.csv"
    if not src.exists():
        return {}
    win = pd.read_csv(src, dtype=str, usecols=["Province", "City"]).dropna()
    win["City"] = win["City"].map(canonical_city)
    win["Province"] = win["Province"].str.upper().str.strip()
    win = win[(win["City"].fillna("") != "") & (win["Province"] != "")]
    return (win.groupby("City")["Province"].agg(lambda s: s.mode().iloc[0])).to_dict()


def load_2007():
    """2007 exists only on Wikipedia (no COMELEC scrape). Governors for ~all provinces, plus the
    cities and municipalities editors filled in."""
    w = _load_wikipedia(2007)
    if w is None:
        print("  (no 2007 source; skipping)")
        return None
    w["year"] = 2007
    munis = w[w["city"] != ""][["province", "city"]].drop_duplicates().shape[0]
    provs = w[w["position"] == "GOVERNOR"]["province"].nunique()
    print(f"  2007: {len(w):,} rows ({provs} provinces w/ governor, {munis} cities/municipalities; Wikipedia)")
    return w


def load_2010():
    """2010 from two sources. The archived COMELEC/Smartmatic results carry every office
    (national and LOCAL) with party but reach ~1,057 municipalities; the Ianmaps tabulation
    reaches more for the national races but has no party. So: keep every Ianmaps national row and
    attach the party a national candidate holds nationwide (taken from COMELEC), add all COMELEC
    LOCAL and party-list rows, and let COMELEC's national rows fill municipalities Ianmaps missed.

    Rappler's /2010/ pages are not used here: they hold 2013 content, not 2010. See
    scrape_2013_mirror.py."""
    ian = _load_ianmaps_2010()
    com = _load_comelec_2010()
    if com is None:
        if ian is None:
            print("  (no 2010 sources; skipping)")
            return None
        out = ian
    else:
        # A national candidate's party is constant everywhere, so learn it once from COMELEC.
        NATIONAL_STR = com["position"].str.contains("PHILIPPINES")
        cand_party = {}
        for name, party in zip(com.loc[NATIONAL_STR, "candidate_name"], com.loc[NATIONAL_STR, "party"]):
            cand_party.setdefault(name, party)
        com_local = com[~NATIONAL_STR]                       # mayor/vice/councilor/gov/board/house
        com_nat = com[NATIONAL_STR]                          # president/VP/senator/party-list
        frames = [com_local, com_nat]
        if ian is not None:
            ian["party"] = [cand_party.get(n, "") for n in ian["candidate_name"]]
            # Match on the CANONICAL locality, not the raw string: the two sources spell some
            # towns differently, and a missed match would keep both national rows and double the
            # votes. COMELEC (with party) wins the overlap; Ianmaps fills only the towns it lacks.
            def _key(prov, city):
                return (resolve_province(prov, city), canonical_city(city))
            covered = {_key(p, c) for p, c in zip(com_nat["province"], com_nat["city"])}
            keep = [_key(p, c) not in covered for p, c in zip(ian["province"], ian["city"])]
            frames.append(ian[keep])
        out = pd.concat(frames, ignore_index=True)

    # Wikipedia fills local executive races the archive never captured, and repairs the few the
    # archive kept only as a fragment (its Manila page tallies the mayor at 217 votes). Key each
    # race on the canonical (province, city, office); add the ones the archive lacks, and where a
    # race exists in both, let the MORE COMPLETE tally win - Wikipedia only displaces the archive
    # when its total is far larger, so a normal archive race is never overwritten by a partial
    # Wikipedia one.
    wiki = _load_wikipedia(2010)
    if wiki is not None:
        def _rkey(prov, city, pos):
            return (resolve_province(prov, city), canonical_city(city), split_position(pos)[0])
        out["_k"] = [_rkey(p, c, pos) for p, c, pos in zip(out["province"], out["city"], out["position"])]
        wiki["_k"] = [_rkey(p, c, pos) for p, c, pos in zip(wiki["province"], wiki["city"], wiki["position"])]
        arch_tot = out.groupby("_k")["votes"].sum()
        new = [k for k in wiki["_k"].unique() if k not in arch_tot.index]
        wiki_tot = wiki.groupby("_k")["votes"].sum()
        repair = [k for k in wiki_tot.index
                  if k in arch_tot.index and wiki_tot[k] > 1.5 * arch_tot[k]]
        take = set(new) | set(repair)
        out = out[~out["_k"].isin(repair)]                   # drop the archive fragments we replace
        added = wiki[wiki["_k"].isin(take)]
        print(f"  2010: +{len(added):,} rows from Wikipedia "
              f"({len(new)} new races, {len(repair)} archive fragments repaired)")
        out = pd.concat([out, added], ignore_index=True).drop(columns="_k")

    race = ["province", "city", "position"]
    tot = out.groupby(race)["votes"].transform("sum")
    out["percentage"] = (100 * out["votes"] / tot.where(tot > 0)).round(2)
    out["rank"] = out.groupby(race)["votes"].rank(ascending=False, method="min").astype(int)
    out["year"] = 2010
    munis = out[out["city"].astype(str).str.strip() != ""][["province", "city"]].drop_duplicates().shape[0]
    print(f"  2010: {len(out):,} rows ({munis} municipalities; COMELEC archive + Ianmaps national)")
    return out


def load_year(year):
    files = sorted(raw_dir(year).rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no raw scrapes under {raw_dir(year)}")

    frames = []
    for f in files:
        d = pd.read_csv(f)
        if not d.empty:
            frames.append(d)

    df = pd.concat(frames, ignore_index=True)
    df["year"] = year
    print(f"  {year}: {len(files):,} municipality files -> {len(df):,} rows")
    return df


def main():
    print("Loading raw scrapes:")
    frames = [load_year(y) for y in VOTE_COUNT_YEARS]
    for extra in (load_2007(), load_2010(), load_2013()):
        if extra is not None:
            frames.append(extra)
    df = pd.concat(frames, ignore_index=True)

    print("\nnormalising:")
    # Keep the source's raw string for traceability, but `position` becomes the canonical
    # office - the same vocabulary the winners dataset uses.
    df["raw_position"] = df["position"]
    parsed = [split_position(p) for p in df["position"]]
    df["position"] = [p[0] for p in parsed]
    df["district"] = [p[1] for p in parsed]

    # An unrecognised office must never ship as a null: that is how BARMM's parliament
    # (a real, 1,155-row office) sat silently discarded in an earlier build.
    unparsed = df[df["position"].isna()]
    if not unparsed.empty:
        names = sorted(unparsed["raw_position"].dropna().unique())
        raise SystemExit(
            f"\n{len(unparsed):,} rows have an office this script does not recognise:\n"
            + "\n".join(f"  {n!r}" for n in names[:20])
            + "\n\nAdd it to OFFICE_PATTERNS rather than letting it through as null."
        )
    print(f"  positions canonicalised: {df['position'].nunique()} distinct, none unparsed")
    print(f"  districts: {df['district'].nunique()} distinct "
          f"({df['district'].notna().sum():,} rows carry one)")

    df["region"] = df["region"].map(canonical_region)
    # resolve_province, not canonical_province: the 2019 feed says only "METRO MANILA",
    # so the NCR district has to be recovered from the city.
    df["province"] = [resolve_province(p, c) for p, c in zip(df["province"], df["city"])]
    df["city"] = df["city"].map(canonical_city)

    # LAV (Local Absentee Voting) and OAV (Overseas Absentee Voting) are real nationwide
    # tallies, not places. Mark them so they can be included in national totals and excluded
    # from geographic aggregation.
    #
    # This has to test the REGION as well as the province. LAV files say LAV/LAV/LAV, so the
    # province alone catches them - but an OAV file says region=OAV, province=EUROPE,
    # city=ITALY. Testing the province alone would let all 63 overseas posts through as
    # genuine Philippine localities, folding overseas votes into national totals and
    # breaking the 1,634-locality invariant, silently, in exactly one cycle.
    df["is_geographic"] = ~(df["province"].isin(NON_GEOGRAPHIC)
                            | df["region"].isin(NON_GEOGRAPHIC))
    non_geo = (~df["is_geographic"]).sum()
    if non_geo:
        found = sorted(NON_GEOGRAPHIC & (set(df["province"].dropna())
                                         | set(df["region"].dropna())))
        print(f"  flagged {non_geo:,} rows as non-geographic tallies ({', '.join(found)})")

    df["is_national_race"] = df["position"].isin(NATIONAL_OFFICES)

    # --- names -------------------------------------------------------------
    # Sources glue the party onto the name ("CRUZ, RODEL (LP)"), and COMELEC truncates at
    # 30 characters, which severs the closing bracket and leaves the party column empty
    # ("SANTANDER-DELOS REYES,LOVE(PFP"). Recover the party from the fragment, strip it
    # from the name, and lift out titles and nicknames - the same canonical name fields
    # the winners dataset carries, so the two are joinable.
    df["reported_name"] = df["candidate_name"]
    is_person = ~df["position"].isin(NON_PERSON_OFFICES)

    parsed = [
        standardize_name(n, p) if person else ("", "", "", "")
        for n, p, person in zip(df["candidate_name"], df["party"], is_person)
    ]
    recovered = [
        clean_reported_name(n, p)[1] if person else None
        for n, p, person in zip(df["candidate_name"], df["party"], is_person)
    ]

    df["last_name"] = [x[0] or None for x in parsed]
    df["first_name"] = [x[1] or None for x in parsed]
    df["middle_name"] = [x[2] or None for x in parsed]
    df["title"] = [x[3] or None for x in parsed]

    # Persons get the canonical "SURNAME, FIRST MIDDLE". Organisations keep their own name,
    # with the ballot number stripped so the same party-list group has one key across
    # cycles (its number changes every election).
    df["candidate_name"] = [
        canonical_full_name(x[0], x[1], x[2]) if person
        else _BALLOT_NUMBER.sub("", str(reported)).strip()
        for x, person, reported in zip(parsed, is_person, df["reported_name"])
    ]

    n_orgs = int((~is_person).sum())
    if n_orgs:
        print(f"  {n_orgs:,} rows are organisations (party-list), not persons: "
              f"name parsing skipped")

    n_recovered = sum(1 for r in recovered if r)
    df["party"] = [r or p for r, p in zip(recovered, df["party"])]
    if n_recovered:
        print(f"  recovered {n_recovered:,} parties from truncated names")

    # --- parties -----------------------------------------------------------
    # The same party is spelled several ways across cycles, which makes it look like it
    # vanished and a candidate look like they switched. Real MERGERS are left alone -
    # see PARTY_ALIASES.
    df["reported_party"] = df["party"]
    before = df["party"].nunique()
    df["party"] = df["party"].map(canonical_party)

    # A party-list group has no party affiliation - it IS the party. Sources disagree on how to
    # say so (GMA writes "GROUP", COMELEC leaves it empty), so set the party column uniformly to
    # the group's own name, which is already in candidate_name (ballot number stripped). That
    # keeps the column complete and groupable rather than a blank that reads as "independent".
    # The source's raw value still survives in reported_party.
    org = df["position"].isin(NON_PERSON_OFFICES)
    df.loc[org, "party"] = df.loc[org, "candidate_name"]

    print(f"  parties canonicalised: {before} -> {df['party'].nunique()} distinct")
    print(f"  names canonicalised; {df['title'].astype(bool).sum():,} titles lifted out")

    # "1.54 %" -> 1.54
    df["percentage"] = pd.to_numeric(
        df["percentage"].astype(str).str.replace("%", "", regex=False).str.strip(),
        errors="coerce",
    )
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce")

    df = drop_duplicate_rows(df, "vote counts")

    columns = [
        "year", "region", "province", "city", "district",
        "position",
        "candidate_name", "last_name", "first_name", "middle_name",
        "title", "party",
        "votes", "percentage", "rank",
        "is_national_race", "is_geographic",
        "raw_position", "reported_name", "reported_party",
    ]
    df = df[columns].sort_values(
        ["year", "region", "province", "city", "position", "votes"],
        ascending=[True, True, True, True, True, False],
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(VOTE_COUNTS_CSV, index=False)

    size_mb = VOTE_COUNTS_CSV.stat().st_size / 1e6
    print(f"\nWrote {VOTE_COUNTS_CSV.name}: {len(df):,} rows, {size_mb:.1f} MB")
    print(df.groupby("year").size().to_string())
    if size_mb > 50:
        print(f"\n  WARNING: {size_mb:.0f} MB exceeds GitHub's 50 MB file limit. "
              f"Host via Zenodo, or split by year / compress.")
    return df


if __name__ == "__main__":
    main()
