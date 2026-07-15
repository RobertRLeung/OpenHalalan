"""
Build what the Dynasties map runs on, from the winners dataset.

    python data/site/build_dynasties.py     -> data/site/dynasty_rates.json
                                                data/site/dynasty_clans.json  (+ report)

Depends on data/site/map_geo.json (for the PSGC codes and the province->region map), so run
build_map_geo.py first. Reuses the geometry's codes so the Dynasties map can draw on exactly
the same boundaries as the results map.

What counts as dynastic here
----------------------------
A seat is dynastic when ANOTHER person in the same unit shares one of its name tokens - a
surname OR a middle name. That one test captures the three ways kinship shows in a Filipino
name:

  last-last     two siblings share a surname.
  last-middle   a married woman carries her maiden name as her middle, so her middle IS her
                birth family's surname - the link a surname-only pass misses, and the reason
                it undercounts families joined through their daughters.
  middle-middle two people share a mother's maiden name as a middle, even where the surname
                differs. This is what a surname pass misses in Mountain Province, whose
                dynasties run through maternal lines - and what a study of the same data found.

The test is PAIRWISE - "does anyone here share a token with me" - and pointedly NOT a
union-find. Chaining shared tokens transitively (A-B by a middle, B-C by a surname, ...)
walks a common maternal name straight across a province and swallows half of it into one
400-person "family". Pairwise cannot chain: two people who share one token are each counted,
but nothing declares them one family. Two unrelated Santos in a town still read as related -
that is the surname-coincidence floor - but the noise stays local, tightest where you zoom
closest.

The rate and the panel part ways on purpose. The RATE, above, is a shaded number and can
afford the loose pairwise net. The detail PANEL prints real people's names, so it groups them
the one plain, defensible way - a shared SURNAME - and never asserts a marriage or maternal
tie it cannot show. So a locality's shaded rate can be a little higher than the surname
families the panel lists add up to; the gap is the marriage and maternal links, counted but
not named.

Thin vs fat, the two shapes of a dynasty
----------------------------------------
  THIN  (sunud-sunod, one after another) - the family holds a seat in a unit across DIFFERENT
        years. Brother A is mayor, then brother B succeeds him. Succession.
  FAT   (sabay-sabay, side by side)       - the family holds two seats in the SAME unit in the
        SAME year. Brother A mayor, brother B vice mayor. Co-occupation.

A winner is dynastic-thin (or -fat) if ANOTHER member of their family also held a seat in the
unit, in a different year (thin) or the same year (fat). Re-election of the same person is
neither - that is incumbency, not a dynasty, and it is excluded by identity.

Three zoom levels, and how far back each reaches
------------------------------------------------
  municipality  the family holds seats in the same TOWN. Cleanest. City is only in the data
                from 2016, so this level is 2016-2025.
  province      the family holds seats anywhere in the PROVINCE. 2004-2025.
  region        the whole region. 2004-2025. Loosest - the widest net for a common name.

Output
------
  dynasty_rates.json   {level: {unitPSGC: {year: [dynastic, fat, thin, total]}}} - the numbers
                       the heatmap colours itself with. Small.
  dynasty_clans.json   {level: {unitPSGC: [clan, ...]}} - the families themselves, for the
                       detail panel: who they are, which offices, which years, thin and/or fat.
"""

import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from config import WINNERS_CSV

HERE = Path(__file__).resolve().parent
GEO = HERE / "map_geo.json"
RATES = HERE / "dynasty_rates.json"
CLANS = HERE / "dynasty_clans.json"
REPORT = HERE / "dynasty_report.txt"

# COMELEC's province label vs the PSGC adm2 unit that holds it - the same aliases the
# results-map crosswalk uses, because the winners carry the same province names.
PROVINCE_ALIAS = {
    "NCR FIRST DISTRICT":  "1303900000",
    "NCR SECOND DISTRICT": "1307400000",
    "NCR THIRD DISTRICT":  "1307500000",
    "NCR FOURTH DISTRICT": "1307600000",
    "COTABATO":            "1204700000",   # the province, not Cotabato City
}
# Maguindanao was one province through 2022 and two from 2025; either half is fine as the
# code for a pre-split winner, since the province and region levels are what use it.
PROVINCE_ALIAS_MULTI = {"MAGUINDANAO": "1908700000"}

CITY_ALIAS = {
    "CORDOBA": "Cordova", "JETAFE": "Getafe", "PINAMUNGAHAN": "Pinamungajan",
    "OZAMIS": "Ozamiz", "BALIUAG": "Baliwag", "MATAAS NA KAHOY": "Mataasnakahoy",
    "BACUNGAN": "Leon T. Postigo", "PIO V CORPUZ": "Pio V. Corpus",
    ("LANAO DEL SUR", "TAGOLOAN"): "Tagoloan II",
}

MUNICIPAL = {"MAYOR", "VICE MAYOR", "COUNCILOR"}
_EMPTY = frozenset()


# Clans shipped per unit in the detail payload, and members per clan. A cap, not a filter of
# the rates - the numbers count everyone; only the panel list is bounded.
TOP_CLANS = 12
TOP_MEMBERS = 12


def fold(s):
    if pd.isna(s):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def city_key(s):
    s = fold(s)
    for pat in (r"^SCIENCE CITY OF ", r"^CITY OF ", r"^MUNICIPALITY OF "):
        s = re.sub(pat, "", s)
    s = re.sub(r" CITY$", "", s)
    s = re.sub(r"^PRES\b", "PRESIDENT", s)
    s = re.sub(r"\bSTO\b", "SANTO", s)
    s = re.sub(r"\bSTA\b", "SANTA", s)
    return s.strip()


def pretty(position):
    return str(position).title().replace("Of", "of").replace("Vice-", "Vice ")


def _clan_detail(g):
    """The families of one unit, for the panel. Grouped by SURNAME only - not by the wider
    token match the rate uses. The rate can afford to be loose because it is just a shaded
    number; the panel prints real people's names, so it groups them the one way that is plain
    and defensible - a shared surname - and asserts no marriage or maternal tie it cannot
    show. Its thin/fat flags are the surname family's OWN co-occurrence, so the label always
    matches the people shown beneath it."""
    import collections as _c
    rows_by_surname = _c.defaultdict(list)
    for r in g.itertuples():
        rows_by_surname[r.surname].append(r)

    fams = []
    for surname, rows in rows_by_surname.items():
        persons = {r.person for r in rows}
        if len(persons) < 2:
            continue
        seats = {(r.person, int(r.Year)) for r in rows}
        fat = any(a != b and ya == yb for (a, ya) in seats for (b, yb) in seats)
        thin = any(a != b and ya != yb for (a, ya) in seats for (b, yb) in seats)
        members = {}
        for r in rows:
            members.setdefault(r.person, {"name": r.full, "seats": set()})
            members[r.person]["seats"].add((int(r.Year), pretty(r.Position)))
        member_list = sorted(
            ({"name": m["name"], "seats": sorted(m["seats"], reverse=True)}
             for m in members.values()),
            key=lambda m: (-len(m["seats"]), m["name"]))
        fams.append({
            "name": surname.title(),
            "people": len(persons),
            "seats": len(rows),
            "fat": fat,
            "thin": thin,
            "members": [{"name": m["name"], "seats": [[y, o] for y, o in m["seats"]]}
                        for m in member_list[:TOP_MEMBERS]],
            "more": max(0, len(member_list) - TOP_MEMBERS),
        })
    fams.sort(key=lambda f: (-f["seats"], -f["people"]))
    return fams



def main():
    log = []

    def say(m):
        print(m)
        log.append(m)

    if not GEO.exists():
        sys.exit("map_geo.json is missing - run build_map_geo.py first")
    geo = json.loads(GEO.read_text())

    prov_name = {p: v["n"] for p, v in geo["adm2"].items()}
    prov_region = {p: v["r"] for p, v in geo["adm2"].items()}   # province PSGC -> region PSGC
    region_name = geo["regions"]
    prov_by_key = {city_key(n): p for p, n in prov_name.items()}
    lgus_by_prov = collections.defaultdict(dict)
    for g in geo["objects"]["lgus"]["geometries"]:
        pr = g["properties"]
        if pr["n"]:
            lgus_by_prov[pr["p"]][city_key(pr["n"])] = pr["id"]

    def province_psgc(name):
        k = fold(name)
        if k in PROVINCE_ALIAS:
            return PROVINCE_ALIAS[k]
        if k in PROVINCE_ALIAS_MULTI:
            return PROVINCE_ALIAS_MULTI[k]
        return prov_by_key.get(city_key(name))

    def city_psgc(prov_code, prov_name_raw, city_raw):
        if prov_code is None or pd.isna(city_raw):
            return None
        table = lgus_by_prov.get(prov_code, {})
        alias = CITY_ALIAS.get((fold(prov_name_raw), fold(city_raw))) or CITY_ALIAS.get(fold(city_raw))
        for key in ([city_key(alias)] if alias else []) + [city_key(city_raw)]:
            if key in table:
                return table[key]
        return None

    # ---------------------------------------------------------------- load & map
    say("reading the winners ...")
    w = pd.read_csv(WINNERS_CSV, low_memory=False)
    w = w[w["Last Name"].notna() & w["First Name"].notna()].copy()
    # Nationwide offices (senator, president, vice president) have no province, so they play
    # no part in a province/town dynasty reading. Drop them before the geography mapping.
    w = w[~w["Position"].isin(["PRESIDENT", "VICE PRESIDENT", "SENATOR"])]

    w["surname"] = w["Last Name"].map(fold)
    w["given"] = w["First Name"].map(fold).str.split().str[0].fillna("")
    w["middle"] = w["Middle Name"].map(fold)          # whole middle name, so DELA CRUZ stays one token
    w = w[(w.surname != "") & (w.given != "")]

    w["prov_code"] = w["Province"].map(province_psgc)
    unmapped = w[w.prov_code.isna()]
    if len(unmapped):
        say(f"  WARNING: {len(unmapped)} rows with an unmapped province: "
            f"{sorted(unmapped['Province'].unique())}")
    w = w[w.prov_code.notna()].copy()
    w["region_code"] = w["prov_code"].map(prov_region)
    w["city_code"] = [city_psgc(pc, pn, c) for pc, pn, c in
                      zip(w.prov_code, w.Province, w.City)]

    muni = w[w.Position.isin(MUNICIPAL)]
    have_city = muni.city_code.notna().mean() * 100
    say(f"  {len(w):,} winner-rows mapped to PSGC; municipal rows with a city: "
        f"{have_city:.0f}% (0% before 2016 by construction)")

    # ---------------------------------------------------------------- the reading
    # A person is one (region, surname, first name), so the same name in two regions is two
    # people and a person re-elected across years is still one.
    w["person"] = w.region_code + "|" + w.surname + "|" + w.given
    w["full"] = w["Full Name"]              # itertuples renames "Full Name"; this stays r.full

    # A seat is dynastic when ANOTHER person in the same unit shares one of its NAME TOKENS.
    # The reader can pick WHICH tokens count, so the reading is computed three ways:
    #
    #   last    share a SURNAME only (last-last). Siblings, a parent and child.
    #   middle  a MIDDLE name is on one side (last-middle or middle-middle): a married woman
    #           whose maiden name IS her middle, or two people sharing a mother's maiden name.
    #           This is the link a surname pass cannot see - and the reason Mountain Province,
    #           dynastic through maternal lines, looks empty without it.
    #   all     either of the above. The default.
    #
    # The test is PAIRWISE - "does someone here share a qualifying token with me" - and
    # pointedly NOT a union-find. Chaining tokens transitively (A-B by a middle, B-C by a
    # surname, ...) walks a common maternal name across a province and merges half of it into
    # one 400-person "family". Pairwise cannot chain: two people who share one token are each
    # counted, but nothing declares them one family.
    MATCHES = ("last", "middle", "all")
    LEVELS = {"region": "region_code", "province": "prov_code", "municipality": "city_code"}
    rates = {lvl: collections.defaultdict(dict) for lvl in LEVELS}
    # fat_flag[lvl][match] / thin_flag[lvl][match] -> set of row indexes
    fat_flag = {lvl: {m: set() for m in MATCHES} for lvl in LEVELS}
    thin_flag = {lvl: {m: set() for m in MATCHES} for lvl in LEVELS}
    detail = {"province": {}, "municipality": {}}

    def scan(buckets, p, y):
        """Given the (year -> persons) dicts a seat could be related through, is there another
        person in the same year (fat) and/or another year (thin)?"""
        fat = thin = False
        for by_year in buckets:
            if by_year is None:
                continue
            if by_year.get(y, _EMPTY) - {p}:
                fat = True
            if any(yy != y and (ps - {p}) for yy, ps in by_year.items()):
                thin = True
        return fat, thin

    for lvl, col in LEVELS.items():
        sub = w[w[col].notna()]
        for unit, g in sub.groupby(col):
            surname_year = collections.defaultdict(lambda: collections.defaultdict(set))
            middle_year = collections.defaultdict(lambda: collections.defaultdict(set))
            for r in g.itertuples():
                surname_year[r.surname][r.Year].add(r.person)
                if r.middle:
                    middle_year[r.middle][r.Year].add(r.person)

            for r in g.itertuples():
                p, y, sn, mid = r.person, r.Year, r.surname, r.middle
                last_b = [surname_year.get(sn)]                       # their surname == mine
                mid_b = [middle_year.get(sn)]                         # their middle == my surname
                if mid:
                    mid_b += [surname_year.get(mid),                  # their surname == my middle
                              middle_year.get(mid)]                   # their middle == my middle
                for m, buckets in (("last", last_b), ("middle", mid_b), ("all", last_b + mid_b)):
                    fat, thin = scan(buckets, p, y)
                    if fat:
                        fat_flag[lvl][m].add(r.Index)
                    if thin:
                        thin_flag[lvl][m].add(r.Index)

            if lvl in detail:
                detail[lvl][unit] = _clan_detail(g)

        # per (unit, year): total, then [both, fat, thin] for each of last / middle / all.
        for (unit, year), g in sub.groupby([col, "Year"]):
            row = [len(g)]
            for m in MATCHES:
                fat, thin = fat_flag[lvl][m], thin_flag[lvl][m]
                row += [int(g.index.isin(fat | thin).sum()),
                        int(g.index.isin(fat).sum()), int(g.index.isin(thin).sum())]
            rates[lvl][unit][int(year)] = row
        tot = sum(r[0] for u in rates[lvl] for r in rates[lvl][u].values())
        dyn = sum(r[7] for u in rates[lvl] for r in rates[lvl][u].values())   # "all" both
        say(f"  {lvl:<13}: {len(rates[lvl]):>4} units, {dyn/tot*100:.1f}% dynastic (both, all-match)")

    clans = {lvl: {u: fams[:TOP_CLANS] for u, fams in units.items() if fams}
             for lvl, units in detail.items()}

    # ---------------------------------------------------------------- write
    RATES.write_text(json.dumps({
        "levels": list(LEVELS),
        "matches": list(MATCHES),
        # each unit-year row is: [total, then (both, fat, thin) for last, middle, all].
        # Index of a (match, relation) numerator: 1 + 3*matchIdx + relIdx, where rel both=0
        # fat=1 thin=2. The map divides that by row[0].
        "fields": "total,l_both,l_fat,l_thin,m_both,m_fat,m_thin,a_both,a_fat,a_thin",
        "regionNames": region_name,
        "rates": {lvl: dict(rates[lvl]) for lvl in LEVELS},
    }, separators=(",", ":")), encoding="utf-8")
    CLANS.write_text(json.dumps(clans, separators=(",", ":")), encoding="utf-8")

    say(f"\nwrote {RATES.name}: {RATES.stat().st_size/1e6:.2f} MB")
    say(f"wrote {CLANS.name}: {CLANS.stat().st_size/1e6:.2f} MB "
        f"(~{CLANS.stat().st_size/4e6:.2f} MB gzipped)")

    # ---------------------------------------------------------------- spot-check
    say("\nspot-check - do the known dynasties surface at province level?")
    for pname, sn in [("Ilocos Norte", "Marcos"), ("NCR Fourth District", "Binay"),
                      ("Davao del Sur", "Duterte"), ("Cebu", "Garcia")]:
        pcode = province_psgc(pname)
        fam = clans["province"].get(pcode, [])
        hit = next((f for f in fam if f["name"].upper() == sn.upper()), None)
        if hit:
            say(f"  {pname:<22} {sn:<10} {hit['people']} people, {hit['seats']} seats, "
                f"{'fat ' if hit['fat'] else ''}{'thin' if hit['thin'] else ''}")
        else:
            say(f"  {pname:<22} {sn:<10} not in top {TOP_CLANS} (rank check needed)")

    REPORT.write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
