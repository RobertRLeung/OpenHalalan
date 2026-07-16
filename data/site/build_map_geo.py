"""
Build the boundary geometry the Explore map draws on.

    python data/site/build_map_geo.py        -> data/site/map_geo.json  (+ map_geo_report.txt)

This is the only script in the repo that reaches the network for something other than
election results, so it is deliberately NOT wired into run_all.py. Boundaries change once
every few years; the ballots change every three. Run it by hand when the PSGC vintage moves.

Where the boundaries come from
------------------------------
faeldon/philippines-json-maps, 2023 PSGC vintage, "medres" (0.01 simplification), MIT.
That repo is itself a re-cut of the PSA/OCHA Common Operational Dataset, which is why every
polygon carries a PSGC code - and a PSGC code, not a name, is what we join votes on. The
data dictionaries have been telling people to do this for a while:

    "Normalise on a stable locality code (PSGC) rather than the name if you need to join
     across cycles."

This script is where the project finally takes its own advice.

The hole in the upstream data, and how it is filled
---------------------------------------------------
The upstream repo publishes municipalities only as a decomposition of their parent province
(municities-provdist-<province>.json). Under PSGC, the 16 highly-urbanised cities are
INDEPENDENT of any province - they are their own adm2 unit - so they appear in no province's
file and fall out of that layer entirely. The eight BARMM Special Geographic Area
municipalities, created in 2024, are missing for the same structural reason.

The result is a 1,618-polygon layer with a Cebu City-, Baguio-, Iloilo City-, Bacolod-,
Davao-sized hole in it. Those are among the largest vote centres in the country; a national
election map without them is not worth drawing.

They do exist upstream, one level down, as barangay decompositions
(bgysubmuns-municity-<lgu>.json). So for those 24 we fetch the barangays and dissolve them
back up into the LGU outline. The dissolve is exact rather than a floating-point union:
in a TopoJSON, two adjacent barangays SHARE an arc, one traversing it forwards and the
other backwards. An arc used twice is therefore interior and an arc used once is on the
LGU's edge. Drop the former, stitch the latter, and you have the city.

Output
------
One TopoJSON, all 1,642 LGUs, quantised onto a single global grid so that arcs shared
between neighbours stay shared (which is what keeps the file small, and what lets the
browser dissolve municipalities into provinces at draw time).
"""

import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path(__file__).resolve().parent / "map_geo.json"
DETAIL = Path(__file__).resolve().parent / "map_geo_prov"   # one hires file per province
REPORT = Path(__file__).resolve().parent / "map_geo_report.txt"
CACHE = Path(__file__).resolve().parent / ".geo_cache"

REPO = "faeldon/philippines-json-maps"
RAW = f"https://raw.githubusercontent.com/{REPO}/master/2023/topojson"
TREE = f"https://api.github.com/repos/{REPO}/git/trees/master?recursive=1"

# "medres" (0.01), not "lowres" (0.001). lowres is not merely coarse, it is destructive:
# it collapses City of San Pedro and Penarrubia to three-point slivers with no interior,
# i.e. it deletes real municipalities. medres costs ~3x the bytes and keeps them.
RES, TOL = "medres", "0.01"

# Names come from the PSA's own register rather than from the boundary file, which does not
# carry a municipality name at the barangay level at all. This is also the check that caught
# a real error: 1030500000 is Cagayan de Oro and 1030900000 is Iligan - the reverse of the
# obvious guess, which would have filed Cagayan de Oro's votes under Lanao del Norte.
PSGC_API = "https://psgc.gitlab.io/api/cities-municipalities/"

# Quantisation grid for the output. The PH bounding box is ~9.7 deg of longitude, so 1e5
# steps puts the grid at ~10 m - far finer than the simplification we are encoding, and
# therefore lossless with respect to the input.
QUANT = 100_000

# The 16 PSGC-independent cities, with the province each one sits INSIDE geographically.
# PSGC gives them no parent - they are their own adm2 unit - but the map still has to file
# them somewhere when you drill into a province, and a reader looking at Cebu expects to
# find Cebu City there. Names below are the PSA's, verified against PSGC_API at build time.
INDEPENDENT_CITY_PARENT = {
    "0330100000": "0305400000",  # City of Angeles         -> Pampanga
    "0331400000": "0307100000",  # City of Olongapo        -> Zambales
    "0431200000": "0405600000",  # City of Lucena          -> Quezon
    "0630200000": "0604500000",  # City of Bacolod         -> Negros Occidental
    "0631000000": "0603000000",  # City of Iloilo          -> Iloilo
    "0730600000": "0702200000",  # City of Cebu            -> Cebu
    "0731100000": "0702200000",  # City of Lapu-Lapu       -> Cebu
    "0731300000": "0702200000",  # City of Mandaue         -> Cebu
    "0831600000": "0803700000",  # City of Tacloban        -> Leyte
    "0931700000": "0907300000",  # City of Zamboanga       -> Zamboanga del Sur
    "1030500000": "1004300000",  # City of Cagayan de Oro  -> Misamis Oriental
    "1030900000": "1003500000",  # City of Iligan          -> Lanao del Norte
    "1230800000": "1206300000",  # City of General Santos  -> South Cotabato
    "1430300000": "1401100000",  # City of Baguio          -> Benguet
    "1630400000": "1600200000",  # City of Butuan          -> Agusan del Norte
    "1731500000": "1705300000",  # City of Puerto Princesa -> Palawan
}

# The BARMM Special Geographic Area. Eight municipalities formed in 2024 out of the 63
# Cotabato barangays that voted to join BARMM in the 2019 plebiscite; they first appear in
# the ballots in 2025. Upstream gives the parent adm2 no name at all, and the PSA's own name
# API predates them, so both the area and its eight municipalities are named here.
SGA_ADM2 = "1909900000"
SGA_NAME = "Special Geographic Area"

# Source: PSA PSGC April 2024 Publication Datafile and Summary of Changes (press release
# 2024-149). The codes are NOT assigned alphabetically - they follow the 2020 interim
# cluster order (Carmen, Kabacan, Midsayap I/II, Pigcawayan, Pikit I/II/III), which is why
# Kadayangan is ...903000 and not ...901000. Do not "fix" this into alphabetical order.
SGA_NAMES = {
    "1999901000": "Kapalawan",       # Carmen cluster,    Bangsamoro Autonomy Act 45
    "1999902000": "Old Kaabakan",    # Kabacan cluster,   BAA 44
    "1999903000": "Kadayangan",      # Midsayap I,        BAA 42
    "1999904000": "Nabalawag",       # Midsayap II,       BAA 43
    "1999905000": "Pahamuddin",      # Pigcawayan cluster, BAA 41
    "1999906000": "Malidegao",       # Pikit I,           BAA 46
    "1999907000": "Ligawasan",       # Pikit II,          BAA 48
    "1999908000": "Tugunan",         # Pikit III,         BAA 47
}

# KNOWN IMPRECISION, boundaries only. The upstream boundaries encode the 2020 INTERIM
# clusters, not the final 2024 municipalities. Three barangays were moved between clusters
# by the acts and the boundary file has not caught up:
#     Dunguan   is drawn inside Tugunan   but belongs to Nabalawag
#     Macabual  is drawn inside Ligawasan but belongs to Tugunan
#     Panicupan is drawn inside Malidegao but belongs to Tugunan
# The votes are joined per MUNICIPALITY, not per barangay, so no vote is misattributed -
# but the drawn edge of those four municipalities is one barangay out. Fixing it properly
# needs a barangay-level union across four separate topologies, which is not worth it for
# three barangays; it is disclosed on the site instead.


def get(url, binary=False):
    """Fetch with a small on-disk cache - this script pulls ~110 files."""
    CACHE.mkdir(exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9.]+", "_", url.split("/master/")[-1])[-120:]
    path = CACHE / name
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "openhalalan-map-build"})
        with urllib.request.urlopen(req, timeout=90) as r:
            path.write_bytes(r.read())
    return json.loads(path.read_text())


# ---------------------------------------------------------------- topojson primitives

def arc_qpoints(topo, i):
    """Arc i as a list of QUANTISED integer points (delta-decoded, still in file space)."""
    x = y = 0
    pts = []
    for dx, dy in topo["arcs"][i]:
        x += dx
        y += dy
        pts.append((x, y))
    return pts


def to_lonlat(topo, pts):
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    return [(x * sx + tx, y * sy + ty) for x, y in pts]


def rings_of(geom):
    """Every ring of a Polygon or MultiPolygon, as lists of signed arc indices."""
    if geom.get("type") is None or "arcs" not in geom:
        return                              # an islet that did not survive simplification
    polys = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
    for poly in polys:
        for ring in poly:
            yield ring


def ring_qpoints(topo, ring):
    """Stitch a ring's arcs into one closed list of quantised points."""
    pts = []
    for a in ring:
        p = arc_qpoints(topo, a if a >= 0 else ~a)
        if a < 0:
            p = p[::-1]
        pts.extend(p[1:] if pts else p)
    return pts


def signed_area(pts):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def contains(ring, pt):
    """Ray casting. Only used to decide which exterior ring a hole belongs to."""
    x, y = pt
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


# ---------------------------------------------------------------- the dissolve

def dissolve(topo, obj):
    """Merge every barangay of one LGU into the LGU outline. Returns MultiPolygon rings
    (lists of lon/lat points). Exact: it works on shared arcs, not on coordinates."""
    use = Counter()
    for g in obj["geometries"]:
        for ring in rings_of(g):
            for a in ring:
                use[a if a >= 0 else ~a] += 1

    # An arc between two barangays is used twice - once each way. An arc used once is on
    # the outside edge of the city. Those are the only ones we keep.
    edge = [a for g in obj["geometries"] for ring in rings_of(g) for a in ring
            if use[a if a >= 0 else ~a] == 1]

    def pts(a):
        p = arc_qpoints(topo, a if a >= 0 else ~a)
        return p[::-1] if a < 0 else p

    by_start = defaultdict(list)
    for a in edge:
        by_start[pts(a)[0]].append(a)

    used, rings = set(), []
    for a0 in edge:
        if a0 in used:
            continue
        chain, a = [], a0
        start = pts(a0)[0]
        while True:
            used.add(a)
            p = pts(a)
            chain.extend(p[1:] if chain else p)
            if p[-1] == start:
                break
            nxt = [b for b in by_start.get(p[-1], []) if b not in used]
            if not nxt:                      # open chain: upstream topology is broken
                raise ValueError("unclosed ring while dissolving")
            a = nxt[0]
        if len(chain) > 3:
            rings.append(chain[:-1])         # drop the repeated closing point

    # Split exterior rings from holes by winding, then file each hole under the exterior
    # ring that contains it.
    outers = [r for r in rings if signed_area(r) > 0]
    holes = [r for r in rings if signed_area(r) <= 0]
    if not outers:                           # everything wound the other way
        outers, holes = holes, []

    polys = [[o] for o in outers]
    for h in holes:
        for poly in polys:
            if contains(poly[0], h[0]):
                poly.append(h)
                break
    return [[to_lonlat(topo, r) for r in poly] for poly in polys]


def polygon_lonlat(topo, geom):
    """A provdist municipality, straight out of its file, as lon/lat rings."""
    polys = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
    return [[to_lonlat(topo, ring_qpoints(topo, ring)) for ring in poly] for poly in polys]


# ---------------------------------------------------------------- build

def clean_adm2_name(n):
    """Upstream labels NCR districts and independent cities '... (Not a Province)'; the site
    never calls them provinces, so drop that parenthetical."""
    if not n:
        return n
    return re.sub(r"\s*\(not a province\)\s*$", "", str(n), flags=re.I).strip()


def collect(res, tol, psgc_name, paths, say):
    """Every LGU and adm2 unit at one resolution, as lon/lat rings."""
    prov_files = [p for p in paths if p.startswith(f"2023/topojson/regions/{res}/")]
    mun_files = [p for p in paths if p.startswith(f"2023/topojson/provdists/{res}/")]
    lgu_files = {re.search(r"municity-(\d+)\.topo", p).group(1).zfill(10): p
                 for p in paths if p.startswith(f"2023/topojson/municities/{res}/")}

    provinces, adm2 = {}, {}
    with ThreadPoolExecutor(8) as pool:
        for topo in pool.map(lambda p: get(f"{RAW}/{p.split('/topojson/')[1]}"), prov_files):
            for obj in topo["objects"].values():
                for g in obj["geometries"]:
                    pr = g["properties"]
                    psgc = str(pr["adm2_psgc"]).zfill(10)
                    # Every adm2 unit gets a name whether or not it has an outline. The
                    # Special Geographic Area has none upstream, and without this it would
                    # drop out of the index the vote join resolves province names against.
                    adm2[psgc] = {"n": clean_adm2_name(pr.get("adm2_en")) or SGA_NAME,
                                  "r": str(pr["adm1_psgc"]).zfill(10)}
                    if g.get("type") is None or "arcs" not in g:
                        continue
                    provinces[psgc] = {"name": adm2[psgc]["n"],
                                       "region": adm2[psgc]["r"],
                                       "rings": polygon_lonlat(topo, g)}

    lgus, empty = {}, []
    with ThreadPoolExecutor(8) as pool:
        for topo in pool.map(lambda p: get(f"{RAW}/{p.split('/topojson/')[1]}"), mun_files):
            for obj in topo["objects"].values():
                for g in obj["geometries"]:
                    pr = g["properties"]
                    psgc = str(pr["adm3_psgc"]).zfill(10)
                    # Kalayaan (the Spratlys) and Limasawa carry null geometries at the
                    # coarser tolerances: their islands do not survive simplification. They
                    # are real municipalities with real votes, so they are recorded rather
                    # than quietly dropped - they simply cannot be drawn at that resolution.
                    if g.get("type") is None or "arcs" not in g:
                        empty.append((psgc, pr.get("adm3_en")))
                        continue
                    lgus[psgc] = {"name": pr["adm3_en"],
                                  "prov": str(pr["adm2_psgc"]).zfill(10),
                                  "reg": str(pr["adm1_psgc"]).zfill(10),
                                  "rings": polygon_lonlat(topo, g)}
    for psgc, name in empty:
        say(f"  no geometry at {res}: {psgc} {name}")

    # The ones a province decomposition structurally cannot reach: the 16 PSGC-independent
    # cities and the 8 SGA municipalities. Dissolve them up out of their barangays.
    missing = sorted(set(lgu_files) - set(lgus))

    def build_missing(psgc):
        topo = get(f"{RAW}/{lgu_files[psgc].split('/topojson/')[1]}")
        obj = next(iter(topo["objects"].values()))
        pr = obj["geometries"][0]["properties"]
        rings = dissolve(topo, obj)
        # An independent city's barangay file names the city itself as its adm2 parent, and
        # an SGA municipality's names the municipality itself. Neither is a province, so
        # neither can be drilled into - both are refiled under the adm2 a reader would look
        # for them in.
        parent = (SGA_ADM2 if psgc in SGA_NAMES
                  else INDEPENDENT_CITY_PARENT.get(psgc, str(pr["adm2_psgc"]).zfill(10)))
        return psgc, {
            # Barangay files carry no LGU name at all, so it comes from the PSA register -
            # or, for the 2024 SGA municipalities the register predates, from SGA_NAMES.
            "name": psgc_name.get(psgc) or SGA_NAMES.get(psgc, ""),
            "prov": parent,
            "reg": str(pr["adm1_psgc"]).zfill(10),
            "rings": rings,
        }

    with ThreadPoolExecutor(8) as pool:
        for psgc, rec in pool.map(build_missing, missing):
            lgus[psgc] = rec
    say(f"  {res}: {len(lgus)} LGUs ({len(missing)} dissolved from barangays), "
        f"{len(adm2)} adm2 units")

    provinces.setdefault(SGA_ADM2, None)
    if provinces[SGA_ADM2] is None:
        del provinces[SGA_ADM2]
    adm2.setdefault(SGA_ADM2, {"n": SGA_NAME, "r": "1900000000"})
    return lgus, provinces, adm2


def main():
    log = []

    def say(msg):
        print(msg)
        log.append(msg)

    say("fetching the upstream file tree ...")
    tree = get(TREE)
    if tree.get("truncated"):
        sys.exit("upstream tree came back truncated; cannot enumerate the LGUs")
    paths = [e["path"] for e in tree["tree"] if e["type"] == "blob"]

    say("fetching PSGC names from the PSA register ...")
    psgc_name = {r["psgc10DigitCode"]: r["name"] for r in get(PSGC_API)}
    say(f"  {len(psgc_name)} cities and municipalities on record")

    # ---------------------------------------------------------------- the national file
    say(f"\nbuilding the national layer at {RES} ...")
    lgus, provinces, adm2 = collect(RES, TOL, psgc_name, paths, say)

    xs = [x for lay in (lgus, provinces) for l in lay.values()
          for poly in l["rings"] for r in poly for x, _ in r]
    ys = [y for lay in (lgus, provinces) for l in lay.values()
          for poly in l["rings"] for r in poly for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = (x1 - x0) / (QUANT - 1), (y1 - y0) / (QUANT - 1)

    def q(pt):
        return (round((pt[0] - x0) / sx), round((pt[1] - y0) / sy))

    arcs, arc_index = [], {}

    def add_arc(pts):
        """One ring -> one arc, deduped both ways round so a border drawn from either side
        collapses to a single arc."""
        qpts = [q(p) for p in pts]
        dedup = [qpts[0]] + [p for a, p in zip(qpts, qpts[1:]) if p != a]
        if len(dedup) < 4:
            return None                      # a sliver with no interior: nothing to fill
        key, rkey = tuple(dedup), tuple(reversed(dedup))
        if key in arc_index:
            return arc_index[key]
        if rkey in arc_index:
            return ~arc_index[rkey]
        arc_index[key] = len(arcs)
        arcs.append(dedup)
        return len(arcs) - 1

    # A few small LGUs do not survive medres - Penarrubia comes through as a 4-point sliver
    # with no interior. Rather than ship the whole country at hires for their sake, take
    # those from the hires pass, where they are intact.
    def degenerate(unit):
        return not any(len({q(p) for p in ring}) >= 3
                       for poly in unit["rings"] for ring in poly)

    # ---------------------------------------------------------------- the detail files
    # The national view is drawn at medres, which is all it can resolve anyway. The moment
    # you zoom into a province, medres is visibly blocky - so each province ALSO gets a
    # hires file, fetched only when someone actually opens that province. 12 MB across all
    # 88, but ~18 KB gzipped for the one you asked for.
    say(f"\nbuilding the per-province detail layer at hires ...")
    hi_lgus, _, _ = collect("hires", "0.1", psgc_name, paths, say)

    DETAIL.mkdir(exist_ok=True)
    for f in DETAIL.glob("*.json"):
        f.unlink()
    by_prov = defaultdict(list)
    for psgc, l in hi_lgus.items():
        by_prov[l["prov"]].append((psgc, l))

    # Quantised and delta-encoded onto the province's own bounding box, exactly as the
    # national file is. Plain GeoJSON floats came to 31 MB across the 88; this is a third
    # of that for the same geometry - a 16-bit grid over one province is sub-metre.
    detail_bytes = 0
    for prov, members in by_prov.items():
        px = [x for _, l in members for poly in l["rings"] for r in poly for x, _ in r]
        py = [y for _, l in members for poly in l["rings"] for r in poly for _, y in r]
        ax0, ax1, ay0, ay1 = min(px), max(px), min(py), max(py)
        psx = (ax1 - ax0) / 65535 or 1e-9
        psy = (ay1 - ay0) / 65535 or 1e-9

        def enc_ring(ring):
            out, lx, ly = [], 0, 0
            for x, y in ring:
                qx, qy = round((x - ax0) / psx), round((y - ay0) / psy)
                out.append([qx - lx, qy - ly])
                lx, ly = qx, qy
            return out

        path = DETAIL / f"{prov}.json"
        path.write_text(json.dumps({
            "transform": {"scale": [psx, psy], "translate": [ax0, ay0]},
            "features": [{
                "id": psgc, "n": l["name"],
                "rings": [[enc_ring(r) for r in poly] for poly in l["rings"]],
            } for psgc, l in sorted(members)],
        }, separators=(",", ":")), encoding="utf-8")
        detail_bytes += path.stat().st_size

    say(f"  wrote {len(by_prov)} province files, {detail_bytes / 1e6:.1f} MB total "
        f"(~{detail_bytes / len(by_prov) / 1e3 / 4:.0f} KB gzipped each, one at a time)")

    broken = [p for p, u in lgus.items() if degenerate(u)]
    if broken:
        say(f"\n{len(broken)} LGU(s) have no interior at {RES}; taking those from hires:")
        for psgc in broken:
            if psgc in hi_lgus:
                lgus[psgc]["rings"] = hi_lgus[psgc]["rings"]
                say(f"   {psgc}  {lgus[psgc]['name']} - recovered from hires")

    # ---------------------------------------------------------------- encode
    objects, dropped = {}, []
    for layer, units in (("lgus", lgus), ("provs", provinces)):
        geoms = []
        for psgc in sorted(units):
            u = units[psgc]
            polys = []
            for poly in u["rings"]:
                ring_arcs = [[a] for a in (add_arc(r) for r in poly) if a is not None]
                if ring_arcs:
                    polys.append(ring_arcs)
            if not polys:
                dropped.append((layer, psgc, u["name"]))
                continue
            props = {"id": psgc, "n": u["name"]}
            props |= ({"p": u["prov"], "r": u["reg"]} if layer == "lgus"
                      else {"r": u["region"]})
            geoms.append({
                "type": "Polygon" if len(polys) == 1 else "MultiPolygon",
                "arcs": polys[0] if len(polys) == 1 else polys,
                "properties": props,
            })
        objects[layer] = {"type": "GeometryCollection", "geometries": geoms}

    for layer, psgc, name in dropped:
        say(f"   DROPPED ({layer}): {psgc} {name or '?'} - no interior after quantisation")

    enc = []
    for a in arcs:
        out, px, py = [], 0, 0
        for x, y in a:
            out.append([x - px, y - py])
            px, py = x, y
        enc.append(out)

    regions = {}
    for g in get(f"{RAW}/country/{RES}/country.topo.{TOL}.json") \
             ["objects"]["PH_Adm1_Regions.shp"]["geometries"]:
        pr = g["properties"]
        regions[str(pr["adm1_psgc"]).zfill(10)] = pr["adm1_en"]

    topo = {
        "type": "Topology",
        "transform": {"scale": [sx, sy], "translate": [x0, y0]},
        "objects": objects,
        "arcs": enc,
        "adm2": adm2,          # every province / NCR district / special, outline or not
        "regions": regions,
    }

    OUT.write_text(json.dumps(topo, separators=(",", ":")), encoding="utf-8")
    mb = OUT.stat().st_size / 1e6
    say(f"\nwrote {OUT.name}: {len(objects['lgus']['geometries'])} LGUs, "
        f"{len(objects['provs']['geometries'])} provinces, {len(arcs)} arcs, {mb:.2f} MB "
        f"(~{mb / 4:.2f} MB gzipped over the wire)")
    REPORT.write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
