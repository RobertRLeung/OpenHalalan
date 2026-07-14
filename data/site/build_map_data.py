"""
Join the ballots to the boundaries, and emit what the Explore map colours itself with.

    python data/site/build_map_data.py       -> data/site/map_data.json (+ map_data_report.txt)

Depends on data/site/map_geo.json, so run build_map_geo.py first.

The join
--------
The vote counts key a locality by NAME - (province, city) - because that is all COMELEC,
GMA and ABS-CBN ever gave us. The boundaries key it by PSGC code. Everything hard about
this script is the bridge between the two, and the bridge has to survive:

  * Alternate names carried in the same string. Canonicalisation flattened "SANTO NINO
    (FAIRE)" to "SANTO NINO FAIRE", so the official name and the old name are now one
    token run. Matched by trying successively shorter prefixes.
  * Source spelling. GMA writes CORDOBA, the PSA writes Cordova; JETAFE / Getafe;
    PINAMUNGAHAN / Pinamungajan; OZAMIS / Ozamiz.
  * Real renames, which are data and not errors: Baliuag -> Baliwag, Bumbaran -> Amai
    Manabilang, Bacungan -> Leon T. Postigo.
  * Provinces that are not provinces. The 16 highly-urbanised cities are their own PSGC
    adm2 unit but COMELEC still files them under the province they sit in. Isabela City is
    filed under Basilan by COMELEC and is its own adm2 unit in PSGC - and is not to be
    confused with the province of Isabela in Luzon.
  * Maguindanao, which was one province through 2022 and two from 2025. Its pre-split
    municipalities are matched across both halves.

Nothing is matched on a guess. Anything the cascade cannot resolve is printed and left
out, and the report says exactly what was dropped and what it was worth in votes.
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import get_close_matches
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from config import VOTE_COUNTS_CSV

HERE = Path(__file__).resolve().parent
GEO = HERE / "map_geo.json"
OUT = HERE / "map_data.json"
REPORT = HERE / "map_data_report.txt"

# The races worth drawing. Councilor and provincial board are multi-seat and municipal-level
# in a way a national choropleth cannot say anything useful about; party list is included
# because "which list topped this town" is a genuinely interesting map.
RACES = ["PRESIDENT", "VICE PRESIDENT", "SENATOR", "PARTY LIST",
         "GOVERNOR", "MAYOR"]

# 2022's national races are held back for the same reason they are held back from the
# Explore table: the scrape captured 7 of 10 presidential candidates and no party list at
# all. Robredo, who came second with ~15M votes, is simply not in it.
WITHHELD = {(2022, "PRESIDENT"), (2022, "VICE PRESIDENT"),
            (2022, "SENATOR"), (2022, "PARTY LIST")}

TOP_N = 6          # candidates kept per locality per race; the rest fold into "others"

# Races whose votes MEAN something when you add up a province. A president, a senator and a
# party list are the same contest in every town, and a governor is one contest per province,
# so summing is just canvassing. A MAYOR is not: Baguio's mayoral race and Itogon's are
# different elections between different people, and adding them together produces a number
# that describes nothing. So the province layer simply does not carry mayor, and the map
# falls back to drawing municipalities when you ask for one.
PROVINCE_LEVEL = {"PRESIDENT", "VICE PRESIDENT", "SENATOR", "PARTY LIST", "GOVERNOR"}

# COMELEC's province for a locality vs the PSGC adm2 unit that actually holds it.
PROVINCE_ALIAS = {
    "NCR FIRST DISTRICT":  ["1303900000"],   # "NCR, City of Manila, First District"
    "NCR SECOND DISTRICT": ["1307400000"],
    "NCR THIRD DISTRICT":  ["1307500000"],
    "NCR FOURTH DISTRICT": ["1307600000"],
    "COTABATO":            ["1204700000"],   # the province - NOT Cotabato City
    # One province through 2022, two from 2025: the plebiscite splitting Maguindanao
    # followed the May 2022 election. Pre-split localities are looked for in both halves.
    "MAGUINDANAO":         ["1908700000", "1908800000"],
    # COMELEC files Isabela City under Basilan; PSGC makes it its own adm2 unit, and it is
    # not the province of Isabela in Luzon.
    "BASILAN":             ["1900700000", "0990100000"],
}

# Spellings and renames the cascade cannot reach on its own. A bare key applies anywhere;
# a (PROVINCE, CITY) key applies only in that province - which matters, because Misamis
# Oriental has a real Tagoloan and Lanao del Sur has a different "Tagoloan II".
CITY_ALIAS = {
    "CORDOBA": "Cordova",                          # GMA's spelling
    "JETAFE": "Getafe",
    "PINAMUNGAHAN": "Pinamungajan",
    "OZAMIS": "Ozamiz",
    "BALIUAG": "Baliwag",                          # renamed 2022
    "MATAAS NA KAHOY": "Mataasnakahoy",
    "BACUNGAN": "Leon T. Postigo",                 # renamed 2005; 2016 still said Bacungan
    "PIO V CORPUZ": "Pio V. Corpus",               # the PSA spells it with an s
    ("LANAO DEL SUR", "TAGOLOAN"): "Tagoloan II",  # not Tagoloan, Misamis Oriental
}


def fold(s):
    """ASCII, upper, no punctuation - the same shape the ballots were canonicalised into."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def city_key(s):
    """Collapse the city/municipality forms of a name onto one key. A place does not stop
    being the same place when it is converted from a municipality into a city."""
    s = fold(s)
    for pat in (r"^SCIENCE CITY OF ", r"^CITY OF ", r"^MUNICIPALITY OF "):
        s = re.sub(pat, "", s)
    s = re.sub(r" CITY$", "", s)
    s = re.sub(r"^PRES\b", "PRESIDENT", s)   # PRES CARLOS P GARCIA / President Carlos P. Garcia
    s = re.sub(r"\bSTO\b", "SANTO", s)       # the PSA abbreviates, COMELEC spells it out
    s = re.sub(r"\bSTA\b", "SANTA", s)
    return s.strip()


def main():
    log = []

    def say(m):
        print(m)
        log.append(m)

    if not GEO.exists():
        sys.exit("map_geo.json is missing - run build_map_geo.py first")

    geo = json.loads(GEO.read_text())
    # adm2 rather than the "provs" geometry layer: the Special Geographic Area has no
    # outline upstream, so it is absent from that layer but present here - and its eight
    # municipalities have votes that have to land somewhere.
    provinces = {p: v["n"] for p, v in geo["adm2"].items()}
    lgus = {}           # psgc -> {name, prov}
    for g in geo["objects"]["lgus"]["geometries"]:
        p = g["properties"]
        lgus[p["id"]] = {"name": p["n"], "prov": p["p"]}
    say(f"geometry: {len(lgus)} LGUs in {len(provinces)} adm2 units")

    # --- indexes to match against -----------------------------------------------------
    prov_by_key = {city_key(n): p for p, n in provinces.items()}
    # "NCR, Second District (Not a Province)" -> also reachable as "NCR SECOND DISTRICT"
    lgus_by_prov = defaultdict(dict)
    for psgc, l in lgus.items():
        if l["name"]:
            lgus_by_prov[l["prov"]][city_key(l["name"])] = psgc

    def province_scopes(name):
        """The PSGC adm2 unit(s) a COMELEC province could mean. More than one only where
        the country genuinely changed shape under it."""
        k = fold(name)
        if k in PROVINCE_ALIAS:
            return PROVINCE_ALIAS[k]
        hit = prov_by_key.get(city_key(name))
        return [hit] if hit else []

    fuzzy_hits = []

    def resolve_city(scopes, city, province):
        """Cascade, most confident first. Returns a PSGC or None - never a guess."""
        raw = city_key(city)
        toks = raw.split()
        # Canonicalisation flattened "OFFICIAL (OLD NAME)" into one token run, so the
        # official name is now a PREFIX of what we hold. Try the longest prefix first.
        forms = [raw] + [" ".join(toks[:i]) for i in range(len(toks) - 1, 0, -1)]

        keys = []
        for f in forms:
            alias = CITY_ALIAS.get((province, f)) or CITY_ALIAS.get(f)
            if alias:
                keys.append(city_key(alias))
            keys.append(f)

        for scope in scopes:
            table = lgus_by_prov.get(scope, {})
            for k in keys:
                if k in table:
                    return table[k]

        # Last resort, and only ever within the province: a near spelling. Every one of
        # these is printed in the report, because a fuzzy match is the one place this
        # script could put a town's votes on the wrong polygon and not know it.
        for scope in scopes:
            table = lgus_by_prov.get(scope, {})
            near = get_close_matches(raw, list(table), n=1, cutoff=0.9)
            if near:
                psgc = table[near[0]]
                fuzzy_hits.append((province, city, lgus[psgc]["name"], psgc))
                return psgc
        return None

    # --- the ballots ------------------------------------------------------------------
    say("reading the ballots ...")
    df = pd.read_csv(VOTE_COUNTS_CSV, low_memory=False,
                     usecols=["year", "region", "province", "city", "position",
                              "candidate_name", "party", "votes"])
    df = df[df.region != "LAV"]              # local absentee voters: a bloc, not a place
    df = df[df.position.isin(RACES)]
    df = df[~df.set_index(["year", "position"]).index.isin(WITHHELD)]
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0).astype(int)
    # Party-list "candidates" are organisations and carry no party of their own, so the
    # column is null for every one of them. groupby() drops null keys, which silently threw
    # away all 660,206 party-list rows until this line existed.
    df["party"] = df["party"].fillna("")
    say(f"  {len(df):,} candidate-rows across {df.city.nunique():,} locality names")

    # --- resolve every (province, city) once ------------------------------------------
    pairs = df[["province", "city"]].drop_duplicates()
    xwalk, unresolved = {}, []
    for _, r in pairs.iterrows():
        scopes = province_scopes(r.province)
        psgc = resolve_city(scopes, r.city, fold(r.province)) if scopes else None
        if psgc:
            xwalk[(r.province, r.city)] = psgc
        else:
            unresolved.append((r.province, r.city))

    say(f"\ncrosswalk: {len(xwalk)} of {len(pairs)} (province, city) pairs resolved to PSGC")

    if fuzzy_hits:
        say(f"\n{len(fuzzy_hits)} matched on a near spelling - check these by eye:")
        for prov, city, psa, psgc in sorted(fuzzy_hits):
            say(f"   {prov:<24} {city:<26} -> {psa} ({psgc})")

    if unresolved:
        lost = df.merge(pd.DataFrame(unresolved, columns=["province", "city"]),
                        on=["province", "city"])
        say(f"\n{len(unresolved)} UNRESOLVED - {lost.votes.sum():,} votes "
            f"({100 * lost.votes.sum() / df.votes.sum():.3f}% of the total) left off the map:")
        for prov, city in sorted(unresolved):
            v = lost[(lost.province == prov) & (lost.city == city)].votes.sum()
            say(f"   {prov:<28} {city:<28} {v:>12,} votes")

    # --- one row per (year, race, locality) -------------------------------------------
    df["psgc"] = [xwalk.get((p, c)) for p, c in zip(df.province, df.city)]
    df = df[df.psgc.notna()]

    cands, cand_index = [], {}

    def cid(name, party):
        key = (name, party)
        if key not in cand_index:
            cand_index[key] = len(cands)
            cands.append([name, party if isinstance(party, str) else ""])
        return cand_index[key]

    # The province a locality is drawn inside. Not the province COMELEC files it under:
    # Cebu City's votes belong in Cebu's provincial total on the map even though PSGC makes
    # the city its own adm2 unit.
    df["prov"] = df.psgc.map(lambda p: lgus[p]["prov"])

    races, cells, pcells = [], [], []
    race_index = {}

    def tally_of(frame):
        t = (frame.groupby(["candidate_name", "party"], as_index=False)["votes"].sum()
                  .sort_values("votes", ascending=False))
        total = int(t.votes.sum())
        if total <= 0:
            return None                      # BARMM parliament rows are all zero; skip
        return total, [[cid(r.candidate_name, r.party), int(r.votes)]
                       for r in t.head(TOP_N).itertuples()]

    for (year, pos), grp in df.groupby(["year", "position"], sort=True):
        race_index[f"{year}|{pos}"] = ri = len(races)
        races.append([int(year), pos])

        for psgc, loc in grp.groupby("psgc"):
            t = tally_of(loc)
            if t:
                cells.append([ri, psgc, t[0], t[1]])

        # Province totals are summed from the FULL ballots, not from the per-locality top
        # six - a candidate who runs sixth in every town would otherwise vanish from the
        # provincial tally he actually leads.
        if pos in PROVINCE_LEVEL:
            for prov, loc in grp.groupby("prov"):
                t = tally_of(loc)
                if t:
                    pcells.append([ri, prov, t[0], t[1]])

    say(f"\n{len(races)} races, {len(cells):,} locality-races, "
        f"{len(pcells):,} province-races, {len(cands):,} candidates")
    for i, (y, p) in enumerate(races):
        n = sum(1 for c in cells if c[0] == i)
        say(f"   {y}  {p:<16} {n:>5} localities")

    covered = {c[1] for c in cells}
    missing = sorted(set(lgus) - covered)
    say(f"\nLGUs with geometry but no result in any race: {len(missing)}")
    for m in missing:
        say(f"   {m}  {lgus[m]['name'] or '(BARMM Special Geographic Area - name unresolved)'}")

    payload = {
        "races": races,          # [[year, position], ...]
        "candidates": cands,     # [[name, party], ...]
        "cells": cells,          # [raceIdx, lguPsgc,  totalVotes, [[candIdx, votes], ...]]
        "pcells": pcells,        # the same, aggregated to the province - see PROVINCE_LEVEL
        "provinceLevel": sorted(PROVINCE_LEVEL),
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    mb = OUT.stat().st_size / 1e6
    say(f"\nwrote {OUT.name}: {mb:.2f} MB (~{mb / 4:.2f} MB gzipped over the wire)")
    REPORT.write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
