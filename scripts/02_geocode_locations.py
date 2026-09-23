"""Step 2: geocode ESMI locations and map them to the IMD / AIFS grids.

Inputs : ESMI location information.csv   528 rows: name, dates, district, state, category, connection type
         data/esmi_locations.csv          locations present in the voltage data (step 1)
         data/locations_manual.csv        OPTIONAL hand corrections: location, lat, lon, note
Outputs: data/locations.csv               one row per ESMI location (see COLUMNS below)
         data/geocode_cache/              cached Nominatim responses + GeoNames India dump
         outputs/02_geocode_review.csv    rows that need a human look (low precision / weak match)
         outputs/figures/02_locations_map.png

Method and decisions (see docs/DATA.md "Location coordinates"):
- ESMI publishes no coordinates. Verschuur & Balakrishnan (2024) geocoded by hand; we geocode
  automatically and flag anything that is not a confident locality-level match, so it can be
  corrected by hand in data/locations_manual.csv (applied last, precision = "manual").
- Name parsing: "<locality>-<city>" (dash with any spacing, or "_"). Names without a dash are tried
  whole and also split as "<first words>, <last 1-2 words>" (e.g. "Ambathur Chennai").
  Sub-unit tags such as (E), (W), (C), (R), (I) are dropped for the query: they are separate meters
  in the same village/town and get the same coordinates.
- Anchor: every candidate must lie near an independent anchor, so a same-named place elsewhere in
  India is rejected. Anchor = the city named in the location string if it geocodes within 80 km of
  the district, otherwise the district itself. Max distance from the anchor: 25 km for urban
  categories anchored on their city, 60 km otherwise (districts are ~50-100 km across, and several
  ESMI district names are outdated, e.g. Warangal and Kancheepuram have since been split).
- Name check: the candidate's own name must resemble the locality (difflib ratio >= 0.6, or one
  contains the other). This stops Nominatim from silently returning the city for an unknown locality.
- Sources, in order: Nominatim (OpenStreetMap, 1 request/s per its usage policy, responses cached),
  then GeoNames India (fuzzy match, ratio >= 0.85, within the anchor radius), then the anchor itself
  (precision "city" or "district").
- Grids: IMD and AIFS share the same 0.25 deg lattice (IMD 6.5-38.5N, 66.5-100E ascending; AIFS
  global, lat 90 -> -90 descending, lon 0-359.75). We store the nearest IMD cell, the nearest IMD
  cell with data (coastal stations can fall on a masked ocean cell), and the AIFS indices.
"""
import difflib
import io
import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import pandas as pd

ROOT = "/scratch/users/ag4680/flood_analysis"
CACHE_DIR = f"{ROOT}/data/geocode_cache"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "esmi-flood-analysis/0.1 (academic research; station geocoding)"
GEONAMES_URL = "https://download.geonames.org/export/dump/IN.zip"
IMD_FILE = f"{ROOT}/RF25_ind2015_rfp25.nc"

URBAN = {"State Capital", "District Headquarters"}
AREA_TYPE = {"State Capital": "urban", "District Headquarters": "urban",
             "Other Municipal Area": "peri-urban", "Gram Panchayat": "rural"}
R_CITY_URBAN, R_OTHER, R_CITY_MAX = 25.0, 60.0, 80.0
MIN_SIM_NOMINATIM, MIN_SIM_GEONAMES = 0.7, 0.88
R_GEONAMES_URBAN, R_GEONAMES_OTHER = 12.0, 45.0
MIN_SIM_IS_CITY = 0.85  # a candidate this similar to the city/district name is the city, not the locality

# ESMI state names -> current names used by OSM
STATE_FIX = {"Andhra Pradesh/Telangana": "Telangana", "Uttaranchal/Uttarakhand": "Uttarakhand",
             "Chandigarh (UT)": "Chandigarh"}
# ESMI district names that are outdated, informal, or sub-district units -> name OSM knows
DISTRICT_FIX = {"Sasaram": "Rohtas", "Faizabad": "Ayodhya", "Gurgaon": "Gurugram",
                "Hoshangabad": "Narmadapuram", "Belgaum": "Belagavi", "Bellary": "Ballari",
                "Bijapur": "Vijayapura", "Anantpur": "Anantapur", "Kamrup Metro": "Kamrup Metropolitan",
                "Rangareddy": "Ranga Reddy", "Mumbai Suburban District": "Mumbai Suburban",
                "Salcete": "South Goa", "Kendujhar": "Kendujhar"}
# words that are not a city when they follow the dash ("Jamui - Town", "Chandauli City")
GENERIC = {"town", "city", "village", "rural", "urban"}
# single words that are never a locality on their own (a query for just "Nagar" or "Pura" matches anything)
GENERIC_LOC_KEYS = {"nagar", "colony", "road", "bazar", "bazaar", "mohalla", "marg", "street", "layout",
                    "vihar", "pura", "puram", "ganj", "tola", "basti", "sector", "ward", "camp", "market",
                    "chowk", "town", "city", "village", "kasba", "housing", "estate", "area", "industrial"}

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(f"{ROOT}/outputs/figures", exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def norm_name(s):
    """Same normalisation as step 1, so names join to esmi_daily / esmi_locations."""
    s = re.sub(r"\s*\[offline\]\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def key(s):
    """Loose comparison key: ascii, lowercase, letters/digits only."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def sim(locality, cand, allow_contain=True):
    """Similarity of a candidate name to the locality. Containment counts only one way: the whole
    locality inside the candidate ("PHC Kanheri Sarap" for "Kanheri Sarap"). The reverse ("Pura" for
    "Puraini", "Guwahati" for "Tarun Nagar Guwahati") is a fragment match and must not score 1."""
    a, b = key(locality), key(cand)
    if not a or not b:
        return 0.0
    if allow_contain and len(a) >= 7 and a in b:  # short keys ("shyam") appear inside unrelated names
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_generic(locality):
    return key(locality) in GENERIC_LOC_KEYS


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- Nominatim (cached, rate-limited)
CACHE_FILE = f"{CACHE_DIR}/nominatim.json"
cache = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}
_last = [0.0]
_new = [0]


def nominatim(q):
    if q in cache:
        return cache[q]
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "countrycodes": "in", "limit": 10, "addressdetails": 1})
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
            break
        except Exception as e:  # network hiccup / 429: back off and retry
            log(f"  nominatim retry {attempt + 1} for {q!r}: {e}")
            time.sleep(5 * (attempt + 1))
    else:
        res = []
    _last[0] = time.time()
    cache[q] = res
    _new[0] += 1
    if _new[0] % 25 == 0:
        json.dump(cache, open(CACHE_FILE, "w"))
    return res


def area_point(q, prefer_admin=False):
    """Centroid of a city / district query: first result, preferring places or admin boundaries."""
    res = nominatim(q)
    if not res:
        return None
    ok = [r for r in res if r.get("category", r.get("class")) in ("boundary", "place")]
    if prefer_admin:
        ok = [r for r in ok if r.get("category", r.get("class")) == "boundary"] or ok
    r = (ok or res)[0]
    return float(r["lat"]), float(r["lon"]), r.get("display_name", "")


# ---------------------------------------------------------------- GeoNames India
def load_geonames():
    path = f"{CACHE_DIR}/IN.txt"
    if not os.path.exists(path):
        log("downloading GeoNames IN.zip")
        req = urllib.request.Request(GEONAMES_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extract("IN.txt", CACHE_DIR)
    cols = ["gid", "name", "asciiname", "alt", "lat", "lon", "fclass", "fcode"]
    g = pd.read_csv(path, sep="\t", header=None, usecols=range(8), names=cols, dtype=str,
                    quoting=3, keep_default_na=False)
    g = g[g.fclass.isin(["P", "A", "L", "S"])].copy()  # populated places, admin, areas, spots
    g["lat"], g["lon"] = g.lat.astype(float), g.lon.astype(float)
    log(f"GeoNames India: {len(g)} places")
    return g.reset_index(drop=True)


def is_city(name, city_names):
    """True if a candidate name is really the city / district the locality belongs to."""
    return any(c and sim(c, name, allow_contain=False) >= MIN_SIM_IS_CITY for c in city_names)


def geonames_match(g, locality, alat, alon, radius, city_names):
    d = 12742 * np.arcsin(np.sqrt(
        np.sin(np.radians(g.lat.values - alat) / 2) ** 2
        + np.cos(np.radians(alat)) * np.cos(np.radians(g.lat.values))
        * np.sin(np.radians(g.lon.values - alon) / 2) ** 2))
    near = g[d <= radius].assign(dist=d[d <= radius])
    best = None
    for r in near.itertuples():
        names = [r.name, r.asciiname] + [a for a in r.alt.split(",") if a and a.isascii()]
        if is_city(r.name, city_names):
            continue
        s = max(sim(locality, n, allow_contain=False) for n in names)
        score = (s, r.fclass == "P", -r.dist)
        if s >= MIN_SIM_GEONAMES and (best is None or score > best[0]):
            best = (score, r)
    if best is None:
        return None
    r = best[1]
    return {"lat": r.lat, "lon": r.lon, "matched_name": r.name, "name_sim": round(best[0][0], 2),
            "match_detail": f"geonames {r.gid} {r.fclass}.{r.fcode}"}


# ---------------------------------------------------------------- name parsing
def parse(name):
    """Return (locality variants, city hint or None)."""
    n = name.replace("_", "-")
    n_noparen = re.sub(r"\s*\([^)]*\)", "", n).strip()           # "Guhagar (C)" -> "Guhagar"
    n_paren = re.sub(r"\(([^)]{4,})\)", r"\1", n)                  # "PEG (Kothrud)" -> "PEG Kothrud"
    city = None
    locs = []
    for s in dict.fromkeys([n_noparen, n_paren]):
        if "-" in s:
            loc, c = s.rsplit("-", 1)
            loc, c = loc.strip(" -"), c.strip()
            c = " ".join(w for w in c.split() if w.lower() not in GENERIC)
            city = city or (c or None)
            if loc:
                locs.append(loc)
        else:
            locs.append(s.strip())
    # "Palghar Town", "Razole Village": also try without the generic word
    locs += [" ".join(w for w in l.split() if w.lower() not in GENERIC) for l in locs]
    words = locs[0].split()
    split_cities = []
    if "-" not in n_noparen and len(words) >= 2:                 # "Ambathur Chennai", "... Jarwal Kasba"
        for k in (1, 2):
            c = " ".join(words[-k:])
            if len(words) > k and c.lower() not in GENERIC:
                split_cities.append((" ".join(words[:-k]), c))
    locs = [re.sub(r"\s+", " ", l) for l in locs if l]
    return list(dict.fromkeys(locs)), city, split_cities


PLACE_CATS = {"place", "boundary", "landuse"}  # areas / settlements, preferred over shops, roads, POIs


def candidates(res, locality, alat, alon, radius, city_names):
    out = []
    for r in res:
        lat, lon = float(r["lat"]), float(r["lon"])
        d = km(lat, lon, alat, alon)
        if d > radius:
            continue
        nm = r.get("name") or r.get("display_name", "").split(",")[0]
        if is_city(nm, city_names) and not sim(locality, nm, allow_contain=False) >= 0.9:
            continue  # Nominatim fell back to the city itself
        s = sim(locality, nm)
        cat = r.get("category", r.get("class"))
        if s >= MIN_SIM_NOMINATIM:
            out.append({"lat": lat, "lon": lon, "matched_name": nm, "name_sim": round(s, 2),
                        "match_detail": f"osm {r.get('osm_type')}/{r.get('osm_id')} {cat}.{r.get('type')}",
                        "osm_display": r.get("display_name", ""), "dist": d, "is_place": cat in PLACE_CATS})
    out.sort(key=lambda c: (-c["name_sim"], not c["is_place"], c["dist"]))
    return out


# ---------------------------------------------------------------- main
meta = pd.read_csv(f"{ROOT}/ESMI location information.csv", dtype=str, encoding="utf-8-sig")
meta.columns = [c.strip() for c in meta.columns]
meta = meta.apply(lambda s: s.str.strip())
meta["location"] = meta["Location name"].map(norm_name)
meta["offline"] = meta["Location name"].str.contains(r"\[offline\]", case=False)
dup = meta[meta.location.duplicated(keep=False)]
if len(dup):
    log(f"WARNING {len(dup)} metadata rows share a normalised name:\n{dup.to_string()}")

esmi = pd.read_csv(f"{ROOT}/data/esmi_locations.csv")
in_data = set(esmi.location)
log(f"metadata locations: {meta.location.nunique()}, in voltage data: {len(in_data)}, "
    f"metadata-only: {len(set(meta.location) - in_data)}, data-only: {len(in_data - set(meta.location))}")
for n in sorted(in_data - set(meta.location)):
    log(f"  in voltage data but not in metadata: {n}")
# Locations with voltage data but no metadata row: district/state taken from the name, dates from the
# voltage data, category unknown (flagged; excluded from the urban/rural split unless filled in).
EXTRA_META = {"Masipidi-Hazaribagh": ("Hazaribagh", "Jharkhand")}
extra = []
for n in sorted(in_data - set(meta.location)):
    if n not in EXTRA_META:
        log(f"  WARNING no district/state known for {n}; it will be missing from locations.csv")
        continue
    e = esmi.set_index("location").loc[n]
    d0, d1 = (pd.to_datetime(e[c]).strftime("%d-%m-%Y") for c in ("first_date", "last_date"))
    extra.append({"Location name": n, "From date": d0, "To date": d1, "District": EXTRA_META[n][0],
                  "State": EXTRA_META[n][1], "Category": "Unknown", "Connection Type": "Unknown",
                  "location": n, "offline": False})
meta = pd.concat([meta, pd.DataFrame(extra)], ignore_index=True)

geonames = load_geonames()
rows = []
for i, m in enumerate(meta.itertuples(index=False)):
    state = STATE_FIX.get(m.State, m.State)
    district = DISTRICT_FIX.get(m.District, m.District)
    locs, city, split_cities = parse(m.location)

    dpt = area_point(f"{district} district, {state}, India", prefer_admin=True) \
        or area_point(f"{district}, {state}, India")
    cpt = None
    for c in [city] + [c for _, c in split_cities]:
        if c:
            p = area_point(f"{c}, {state}, India")
            if p and (dpt is None or km(p[0], p[1], dpt[0], dpt[1]) <= R_CITY_MAX):
                cpt, city = p, c
                break
    if cpt:
        anchor, anchor_type = cpt, "city"
        radius = R_CITY_URBAN if m.Category in URBAN else R_OTHER
    elif dpt:
        anchor, anchor_type, radius = dpt, "district", R_OTHER
    else:
        anchor, anchor_type, radius = None, "none", None

    best, query_used = None, None
    city_names = [city, m.District, district] + [c for _, c in split_cities]
    if anchor:
        queries = []
        for loc in locs:
            if city:
                queries.append((loc, f"{loc}, {city}, {state}, India"))
            queries += [(loc, f"{loc}, {district}, {state}, India"), (loc, f"{loc}, {state}, India")]
        for loc, c in split_cities:
            queries.append((loc, f"{loc}, {c}, {state}, India"))
        queries = [(l, q) for l, q in dict.fromkeys(queries) if not is_generic(l)]
        for loc, q in queries:
            cs = candidates(nominatim(q), loc, anchor[0], anchor[1], radius, city_names)
            if cs:
                best, query_used = cs[0], q
                best["source"] = "nominatim"
                break
        if best is None:
            for loc in dict.fromkeys(locs + [l for l, _ in split_cities]):
                if is_generic(loc) or len(key(loc)) < 4:
                    continue
                # GeoNames is mostly villages: an urban neighbourhood must match close to its city,
                # otherwise it picks up a same-sounding village 20-60 km away
                g_radius = min(radius, R_GEONAMES_URBAN if m.Category in URBAN else R_GEONAMES_OTHER)
                gm = geonames_match(geonames, loc, anchor[0], anchor[1], g_radius, city_names)
                if gm:
                    best, query_used = gm, f"geonames: {loc}"
                    best["source"] = "geonames"
                    break

    if best:
        precision = "locality"
    elif anchor:
        best = {"lat": anchor[0], "lon": anchor[1], "matched_name": anchor[2].split(",")[0],
                "name_sim": np.nan, "match_detail": f"{anchor_type} centroid", "source": "nominatim"}
        precision, query_used = anchor_type, "(anchor fallback)"
    else:
        best, precision = {"lat": np.nan, "lon": np.nan, "source": "none"}, "none"

    rows.append({
        "location": m.location, "raw_name": m._0, "locality_query": locs[0], "city_hint": city,
        "district": m.District, "state": m.State, "state_osm": state, "district_osm": district,
        "category": m.Category, "area_type": AREA_TYPE.get(m.Category), "connection_type": m._6,
        "from_date": pd.to_datetime(m._1, format="%d-%m-%Y").date(),
        "to_date": pd.to_datetime(m._2, format="%d-%m-%Y").date(),
        "offline": m.offline, "in_voltage_data": m.location in in_data,
        "lat": best["lat"], "lon": best["lon"], "precision": precision, "source": best["source"],
        "matched_name": best.get("matched_name"), "name_sim": best.get("name_sim"),
        "match_detail": best.get("match_detail"), "osm_display": best.get("osm_display"),
        "query": query_used, "anchor_type": anchor_type,
        "anchor_lat": anchor[0] if anchor else np.nan, "anchor_lon": anchor[1] if anchor else np.nan,
        "dist_to_anchor_km": round(km(best["lat"], best["lon"], anchor[0], anchor[1]), 1)
        if anchor and precision == "locality" else 0.0,
        "district_to_city_km": round(km(cpt[0], cpt[1], dpt[0], dpt[1]), 1) if cpt and dpt else np.nan,
    })
    if (i + 1) % 25 == 0:
        log(f"{i + 1}/{len(meta)} done; new Nominatim requests so far: {_new[0]}")
json.dump(cache, open(CACHE_FILE, "w"))

loc = pd.DataFrame(rows)

# manual corrections win
man_path = f"{ROOT}/data/locations_manual.csv"
if os.path.exists(man_path):
    man = pd.read_csv(man_path)
    for r in man.itertuples():
        sel = loc.location == r.location
        loc.loc[sel, ["lat", "lon", "precision", "source", "query"]] = \
            [r.lat, r.lon, "manual", "manual", getattr(r, "note", "")]
    log(f"applied {len(man)} manual corrections")

# ---------------------------------------------------------------- grid lookup
import xarray as xr  # noqa: E402

imd = xr.open_dataset(IMD_FILE)
ilat, ilon = imd.LATITUDE.values, imd.LONGITUDE.values
valid = imd.RAINFALL.notnull().any("TIME").values  # land cells with data
vi, vj = np.nonzero(valid)
for c in ["imd_i", "imd_j", "imd_lat", "imd_lon", "imd_valid_i", "imd_valid_j",
          "imd_valid_km", "aifs_lat_idx", "aifs_lon_idx"]:
    loc[c] = np.nan
loc["imd_valid"] = pd.Series(pd.NA, index=loc.index, dtype="boolean")
for k, r in loc[loc.lat.notna()].iterrows():
    i = int(np.abs(ilat - r.lat).argmin())
    j = int(np.abs(ilon - r.lon).argmin())
    d = [km(r.lat, r.lon, ilat[a], ilon[b]) for a, b in zip(vi, vj)]
    n = int(np.argmin(d))
    loc.loc[k, ["imd_i", "imd_j", "imd_lat", "imd_lon", "imd_valid"]] = [i, j, ilat[i], ilon[j], valid[i, j]]
    loc.loc[k, ["imd_valid_i", "imd_valid_j", "imd_valid_km"]] = [vi[n], vj[n], round(d[n], 1)]
    loc.loc[k, "aifs_lat_idx"] = int(round((90 - ilat[i]) / 0.25))  # AIFS lat is 90 -> -90
    loc.loc[k, "aifs_lon_idx"] = int(round(ilon[j] / 0.25))         # AIFS lon is 0 -> 359.75
for c in ["imd_i", "imd_j", "imd_valid_i", "imd_valid_j", "aifs_lat_idx", "aifs_lon_idx"]:
    loc[c] = loc[c].astype("Int64")

loc.to_csv(f"{ROOT}/data/locations.csv", index=False)
log(f"wrote data/locations.csv ({len(loc)} rows)")

# ---------------------------------------------------------------- QA
review = loc[(loc.precision != "locality") & (loc.precision != "manual")
             | (loc.name_sim < 0.8) | (loc.dist_to_anchor_km > 40)
             | ((loc.source == "geonames") & (loc.name_sim < 1))]  # fuzzy village-name matches
review.to_csv(f"{ROOT}/outputs/02_geocode_review.csv", index=False)
used = loc[loc.connection_type != "Agriculture"]
print("\nprecision (all rows):\n", loc.precision.value_counts().to_string())
print("\nsource x precision:\n", pd.crosstab(loc.source, loc.precision).to_string())
print("\nprecision by area type (excluding Agriculture):\n",
      pd.crosstab(used.area_type, used.precision).to_string())
print(f"\nrows flagged for review: {len(review)} -> outputs/02_geocode_review.csv")
print(f"stations whose nearest IMD cell has no data (coastal): {int((loc.imd_valid == False).sum())}")

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

fig, ax = plt.subplots(figsize=(8, 8.5))
ax.pcolormesh(ilon, ilat, np.where(valid, 1, np.nan), cmap="Greys", vmin=0, vmax=4, shading="nearest")
style = {"locality": ("#1b7837", "o"), "manual": ("#2166ac", "o"),
         "city": ("#e08214", "s"), "district": ("#b2182b", "^")}
for p, (col, mk) in style.items():
    s = loc[loc.precision == p]
    if len(s):
        ax.scatter(s.lon, s.lat, s=14, c=col, marker=mk, label=f"{p} ({len(s)})",
                   edgecolor="white", linewidth=0.3)
ax.set(xlim=(66, 98), ylim=(6.5, 36.5), xlabel="Longitude (°E)", ylabel="Latitude (°N)",
       title="ESMI locations by geocoding precision\n(grey = IMD 0.25° land cells)")
ax.legend(loc="lower left", frameon=False, title="precision")
ax.set_aspect("equal")
fig.tight_layout()
fig.savefig(f"{ROOT}/outputs/figures/02_locations_map.png", dpi=150)
log("wrote outputs/figures/02_locations_map.png")
