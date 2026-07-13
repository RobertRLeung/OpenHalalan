"""
Canonical place names, region backfill and de-duplication.

COMELEC relabels places between cycles, so the same locality arrives under a different
string each year. Left alone, a longitudinal group-by shatters one place into several
unrelated panels. Everything here exists to give each real place ONE stable key.

Applied by build_vote_counts.py and merge_winners.py. Import from either.
"""

import re
import unicodedata

import pandas as pd

# ---------------------------------------------------------------------------
# Non-geographic tally categories
# ---------------------------------------------------------------------------
# LAV = Local Absentee Voting: government employees, media, military and police who vote
# away from their home precinct. COMELEC reports it as if it were a place (region ==
# province == city == "LAV"), but it is a nationwide category. It legitimately contains
# only SENATOR and PARTY LIST rows, because absentee voters may vote for national offices
# only. Real data - keep it, but never treat it as a province.
NON_GEOGRAPHIC = {"LAV", "OAV"}  # OAV = Overseas Absentee Voting, if it ever appears


# ---------------------------------------------------------------------------
# Provinces
# ---------------------------------------------------------------------------
# The National Capital Region has FOUR legislative districts. Every cycle names them
# differently, and the 1st district (the City of Manila) is the worst offender.
NCR_DISTRICTS = {
    # 1st district IS the City of Manila.
    "NCR CITY OF MANILA FIRST DISTRICT": "NCR FIRST DISTRICT",
    "NCR MANILA": "NCR FIRST DISTRICT",
    "NCR FIRST DISTRICT": "NCR FIRST DISTRICT",
    "NCR SECOND DISTRICT": "NCR SECOND DISTRICT",
    "NCR THIRD DISTRICT": "NCR THIRD DISTRICT",
    "NCR FOURTH DISTRICT": "NCR FOURTH DISTRICT",
    # In 2022 COMELEC broke Taguig and Pateros out as their own pseudo-province. They
    # belong to the 4th district, where the 2025 scrape puts them back.
    "TAGUIG PATEROS": "NCR FOURTH DISTRICT",
}

# Renames of the same territory. Keys are already ascii-folded and space-collapsed.
PROVINCE_RENAMES = {
    # Renamed in 2019; the same province either way.
    "COMPOSTELA VALLEY": "DAVAO DE ORO",

    # ABS-CBN's 2019 feed disambiguates three provinces with a parenthetical. There is NO
    # consistent rule for which half is the canonical name - sometimes it is the prefix
    # ("COTABATO"), sometimes the parenthetical ("DAVAO DEL NORTE") - so map them
    # explicitly rather than trying to strip the brackets.
    "COTABATO NORTH COT": "COTABATO",
    "DAVAO DAVAO DEL NORTE": "DAVAO DEL NORTE",
    "SAMAR WESTERN SAMAR": "SAMAR",
}

# NOT renames, and deliberately absent from the map above:
#   MAGUINDANAO -> MAGUINDANAO DEL NORTE / DEL SUR is a genuine SPLIT into two provinces.
#   The plebiscite followed the May 2022 election, so 2004-2022 correctly show one
#   undivided province and 2025 correctly shows two. Merging them would be wrong.


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------
REGION_CANON = {
    # ARMM was abolished and succeeded by BARMM in 2019. Same territory, one key.
    "AUTONOMOUS REGION IN MUSLIM MINDANAO": "BARMM",
    "ARMM": "BARMM",
    "BARMM": "BARMM",
    "NATIONAL CAPITAL REGION": "NATIONAL CAPITAL REGION",
    "NCR": "NATIONAL CAPITAL REGION",
    "CORDILLERA ADMINISTRATIVE REGION": "CORDILLERA ADMINISTRATIVE REGION",
    "CAR": "CORDILLERA ADMINISTRATIVE REGION",
    # Negros Island Region, created 2024 out of Regions VI and VII. Genuinely new: a
    # province's region legitimately CHANGES between 2022 and 2025. Not an error.
    "NIR": "NEGROS ISLAND REGION",
    "NEGROS ISLAND REGION": "NEGROS ISLAND REGION",
}


def _fold(value):
    """Upper-case, strip accents, collapse punctuation and whitespace."""
    if pd.isna(value):
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))  # PENARRUBIA
    text = text.upper().replace("-", " ").replace(",", " ").replace(".", " ")
    # Brackets become spaces so a parenthetical qualifier folds into one flat key:
    # "COTABATO (NORTH COT )" -> "COTABATO NORTH COT". See PROVINCE_RENAMES.
    text = text.replace("(", " ").replace(")", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def canonical_region(value):
    folded = _fold(value)
    if folded is None:
        return None
    return REGION_CANON.get(folded, folded)


def canonical_province(value):
    folded = _fold(value)
    if folded is None:
        return None
    if folded in NON_GEOGRAPHIC:
        return folded
    folded = folded.replace("NATIONAL CAPITAL REGION", "NCR")
    if folded in NCR_DISTRICTS:
        return NCR_DISTRICTS[folded]
    return PROVINCE_RENAMES.get(folded, folded)


# Metro Manila's 17 LGUs and the NCR legislative district each belongs to.
#
# The 2022/2025 COMELEC feeds name the district directly, but the 2019 ABS-CBN feed only
# says "METRO MANILA". Without this map NCR fragments across cycles again - the exact
# defect the province canonicalisation exists to prevent.
NCR_CITY_TO_DISTRICT = {
    # 1st district IS the City of Manila.
    "MANILA": "NCR FIRST DISTRICT",
    # 2nd
    "MANDALUYONG": "NCR SECOND DISTRICT",
    "MARIKINA": "NCR SECOND DISTRICT",
    "PASIG": "NCR SECOND DISTRICT",
    "SAN JUAN": "NCR SECOND DISTRICT",
    "QUEZON": "NCR SECOND DISTRICT",  # QUEZON CITY, folded to QUEZON by canonical_city
    # 3rd
    "CALOOCAN": "NCR THIRD DISTRICT",
    "MALABON": "NCR THIRD DISTRICT",
    "NAVOTAS": "NCR THIRD DISTRICT",
    "VALENZUELA": "NCR THIRD DISTRICT",
    # 4th
    "LAS PINAS": "NCR FOURTH DISTRICT",
    "MAKATI": "NCR FOURTH DISTRICT",
    "MUNTINLUPA": "NCR FOURTH DISTRICT",
    "PARANAQUE": "NCR FOURTH DISTRICT",
    "PASAY": "NCR FOURTH DISTRICT",
    "TAGUIG": "NCR FOURTH DISTRICT",
    "PATEROS": "NCR FOURTH DISTRICT",
}

# Province values that mean "somewhere in Metro Manila" without saying which district.
NCR_UMBRELLA = {"METRO MANILA", "NCR", "NATIONAL CAPITAL REGION"}


def resolve_province(province, city):
    """
    Canonical province, resolving a bare "METRO MANILA" to the city's NCR district.

    Sources that already name the district (COMELEC 2022/2025) pass through unchanged.
    """
    prov = canonical_province(province)
    if prov in NCR_UMBRELLA:
        return NCR_CITY_TO_DISTRICT.get(canonical_city(city), prov)
    return prov


def canonical_city(value):
    folded = _fold(value)
    if folded is None:
        return None
    # COMELEC writes both "CALACA" and "CITY OF CALACA" for the same locality across
    # cycles as municipalities are converted to cities. Strip the honorific so the place
    # keeps one key; the conversion itself is a real event, recorded in the audit.
    folded = re.sub(r"^CITY OF ", "", folded)
    folded = re.sub(r" CITY$", "", folded)
    return folded


def backfill_region(df, province_col="Province", region_col="Region"):
    """
    Fill a missing Region from the province, using the mapping the other cycles agree on.

    2019 arrives with Region null for all 18,134 rows. Every one of its 86 provinces
    appears in another cycle, so the region is recoverable rather than lost.
    """
    known = (
        df[df[region_col].notna()]
        .groupby(province_col)[region_col]
        .agg(lambda s: s.mode().iloc[0])
    )
    missing = df[region_col].isna()
    df.loc[missing, region_col] = df.loc[missing, province_col].map(known)
    return df, int(missing.sum()), int(df[region_col].isna().sum())


def drop_duplicate_rows(df, label=""):
    """Remove exact duplicate rows, reporting what went."""
    before = len(df)
    df = df.drop_duplicates(ignore_index=True)
    removed = before - len(df)
    if removed:
        print(f"  dropped {removed:,} exact duplicate rows{f' ({label})' if label else ''}")
    return df


def normalize_places(df, province="Province", region="Region", city=None):
    """Apply canonical place names in place. Returns the frame."""
    if region in df.columns:
        df[region] = df[region].map(canonical_region)
    if province in df.columns:
        df[province] = df[province].map(canonical_province)
    if city and city in df.columns:
        df[city] = df[city].map(canonical_city)
    return df
