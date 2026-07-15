"""
Build what the Dynasties map runs on, from the winners dataset.

    python data/site/build_dynasties.py     -> data/site/dynasty_rates.json
                                                data/site/dynasty_clans.json  (+ report)

Depends on data/site/map_geo.json (for the PSGC codes and the province->region map), so run
build_map_geo.py first. Reuses the geometry's codes so the Dynasties map can draw on exactly
the same boundaries as the results map.

What a "dynasty" is here
------------------------
Two winners are treated as the same political family when they share a surname within one
region. That is it, for this proof of concept. It is surname matching, so it is not kinship:
two unrelated CRUZ families in one region read as one, and the map says so.

Marriage linking - joining families through the maiden name a married woman carries as her
MIDDLE name - was tried and pulled. Chained through a union-find it merged unrelated families
into region-sized blobs and pushed the dynastic rate past 80%, and post-2016 the middle name
is filled on barely one row in eight, so it cannot be applied evenly. It belongs in a later
version, as an edge between families rather than a merge of them.

Thin vs fat, the two shapes of a dynasty
----------------------------------------
  THIN  (sunud-sunod, one after another) - the family holds a seat in a jurisdiction across
        DIFFERENT years. Brother A is mayor, then brother B succeeds him. Succession.
  FAT   (sabay-sabay, side by side)       - the family holds two seats in the SAME
        jurisdiction in the SAME year. Brother A mayor, brother B vice mayor. Co-occupation.

A winner is dynastic-thin (or -fat) in a unit if ANOTHER member of their family also held a
seat in that unit, in a different year (thin) or the same year (fat). Re-election of the same
person is neither - that is incumbency, not a dynasty, and it is excluded by identity.

Three zoom levels, because the map has three
--------------------------------------------
The reading is computed at every level the map can show, and the family co-occupation test is
scoped to the unit in view - so the surname noise is tightest where you look closest:

  municipality  the family holds seats in the same TOWN. Clean - two same-surname winners in
                one small town are almost certainly kin.
  province      the family holds seats anywhere in the PROVINCE. Looser: two same-surname
                mayors of different towns count, related or not.
  region        the whole region. Looser still.

2016-2025 only, so every winner carries a city and all three levels span the same four cycles
as the results map. Extending back to 2004 needs town-level winners for the older cycles,
which do not exist yet (the ListElected scrape). See FIRST_YEAR.

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

# Proof of concept: 2016 on, so all three zoom levels span the same four cycles as the
# results map, and every municipal winner carries a city. Extending back to 2004 needs
# town-level winners for the older cycles, which do not exist yet - see the ListElected
# scrape. When it lands, drop this and the map gains four more cycles at province/region.
FIRST_YEAR = 2016

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
    w = w[w.Year >= FIRST_YEAR]
    w = w[w["Last Name"].notna() & w["First Name"].notna()].copy()

    w["surname"] = w["Last Name"].map(fold)
    w["given"] = w["First Name"].map(fold).str.split().str[0].fillna("")
    w["middle"] = w["Middle Name"].map(fold).str.split().str[0].fillna("")
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

    # ---------------------------------------------------------------- families
    # A person is identified within their region, so the same name in two regions is two
    # people. A family is a surname within a region - nothing more for this proof of concept.
    #
    # Marriage linking (a maiden name carried as a middle name) is deliberately NOT done here.
    # Chaining it through a union-find merged unrelated families into region-sized blobs and
    # pushed the dynastic rate past 80%, and post-2016 the middle name is filled on barely one
    # row in eight, so it cannot be done evenly. It belongs in a later version, as an edge
    # between clans rather than a merge of them.
    w["person"] = w.region_code + "|" + w.surname + "|" + w.given
    w["clan"] = w.region_code + "|" + w.surname
    say(f"  families: {w.clan.nunique():,} surname-clans across {w.region_code.nunique()} regions")

    # ---------------------------------------------------------------- the reading
    LEVELS = {"region": "region_code", "province": "prov_code", "municipality": "city_code"}
    rates = {lvl: collections.defaultdict(dict) for lvl in LEVELS}
    fat_flag = {lvl: set() for lvl in LEVELS}
    thin_flag = {lvl: set() for lvl in LEVELS}

    for lvl, col in LEVELS.items():
        sub = w[w[col].notna()]

        # FAT is a pure count: a seat is fat when its (unit, clan, year) holds two or more
        # DISTINCT people. That is a groupby transform, no Python loop.
        n_people_ucy = sub.groupby([col, "clan", "Year"]).person.transform("nunique")
        fat_flag[lvl] = set(sub.index[n_people_ucy >= 2])

        # THIN needs another family member in a DIFFERENT year, so it is scoped per
        # (unit, clan). The groups are tiny, so the set work below is cheap - and it is set
        # work, not iterrows, which is what made the first cut take minutes.
        for (unit, clan), g in sub.groupby([col, "clan"]):
            if g.person.nunique() < 2:
                continue                     # a lone name is not a dynasty
            years = g.Year.values
            persons = g.person.values
            by_year = collections.defaultdict(set)
            for pr, yr in zip(persons, years):
                by_year[yr].add(pr)
            # people active in each year, so "elsewhere" = everyone minus this year's set...
            for idx, pr, yr in zip(g.index, persons, years):
                # another person, in some other year
                if any(yy != yr and (ps - {pr}) for yy, ps in by_year.items()):
                    thin_flag[lvl].add(idx)

        both_set = fat_flag[lvl] | thin_flag[lvl]
        for (unit, year), g in sub.groupby([col, "Year"]):
            fat = g.index.isin(fat_flag[lvl]).sum()
            thin = g.index.isin(thin_flag[lvl]).sum()
            both = g.index.isin(both_set).sum()
            rates[lvl][unit][int(year)] = [int(both), int(fat), int(thin), len(g)]

        counts = [rates[lvl][u][y] for u in rates[lvl] for y in rates[lvl][u]]
        tot = sum(c[3] for c in counts)
        dyn = sum(c[0] for c in counts)
        say(f"  {lvl:<13}: {len(rates[lvl]):>4} units, "
            f"{dyn/tot*100:.1f}% of seats dynastic overall")

    # ---------------------------------------------------------------- clan detail
    w["is_fat_prov"] = w.index.isin(fat_flag["province"])
    w["is_thin_prov"] = w.index.isin(thin_flag["province"])
    w["is_fat_muni"] = w.index.isin(fat_flag["municipality"])
    w["is_thin_muni"] = w.index.isin(thin_flag["municipality"])

    def clans_for(col, fatset, thinset):
        out = {}
        sub = w[w[col].notna()]
        for unit, g in sub.groupby(col):
            fams = []
            for clan, cg in g.groupby("clan"):
                if cg.person.nunique() < 2:
                    continue
                members = []
                for person, pg in cg.groupby("person"):
                    seats = sorted({(int(r.Year), pretty(r.Position)) for r in pg.itertuples()},
                                   reverse=True)
                    name = pg.iloc[0]["Full Name"]
                    members.append({"name": name,
                                    "seats": [[y, o] for y, o in seats]})
                members.sort(key=lambda m: (-len(m["seats"]), m["name"]))
                fams.append({
                    "name": cg.iloc[0]["surname"].title(),
                    "people": cg.person.nunique(),
                    "seats": len(cg),
                    "fat": bool(cg.index.isin(fatset).any()),
                    "thin": bool(cg.index.isin(thinset).any()),
                    "members": members[:TOP_MEMBERS],
                    "more": max(0, len(members) - TOP_MEMBERS),
                })
            fams.sort(key=lambda f: (-f["seats"], -f["people"]))
            if fams:
                out[unit] = fams[:TOP_CLANS]
        return out

    clans = {
        "province": clans_for("prov_code", fat_flag["province"], thin_flag["province"]),
        "municipality": clans_for("city_code", fat_flag["municipality"], thin_flag["municipality"]),
    }

    # ---------------------------------------------------------------- write
    RATES.write_text(json.dumps({
        "levels": list(LEVELS),
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
