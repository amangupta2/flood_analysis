"""Match Global Flood Database (GFD) events to ESMI stations.

Rebuilds the Verschuur & Balakrishnan (2024) event list: a GFD event affects a station when
there is flooding near it AND the event falls inside the station's ESMI coverage.
The authors did not share their list, so this is our own reconstruction.

Inputs
  data/locations.csv            station coordinates (scripts/02_geocode_locations.py)
  data/esmi_daily.csv.gz        daily outage panel (scripts/01_esmi_profile_daily.py)
  data/gfd/tif/DFO_*.tif        GFD footprints (flooded, duration, clear_views, clear_perc, jrc_perm_water)
  data/gfd/gfd_qcdatabase.csv   GFD event table

Outputs
  data/flood_event_stations.csv one row per (event, station with any flooding within 30 km)
  data/flood_events.csv         one row per event with station counts
  outputs/04_flood_matching_log.txt   decisions and counts
  outputs/figures/04_flood_events_map.png

Decisions
  * Flooded pixel = GFD `flooded` == 1 AND NOT JRC permanent water.
  * River-channel mask (owner decision, 2026-09-23): GFD `flooded` also picks up seasonally wet
    river channels that JRC does not call permanent (first run: the 11 Guwahati stations sat
    1-2 km from the Brahmaputra and "matched" 6 unrelated events, including one in March).
    Pixels flooded in >= RECUR_MIN of the 26 downloaded events are treated as recurrent river
    water and ignored. Every event footprint is resampled (nearest) onto one common grid per
    station so the recurrence count lines up pixel by pixel.
  * Primary rule: a station is affected if >= MIN_KM2 of (masked) flooding lies within 20 km.
    Sensitivity rule ("raw"): any unmasked flooded pixel within 20 km, as in the paper.
  * Distances use an equirectangular approximation; fine at < 50 km.
  * Event window = GFD Began - 3 d to Ended + 3 d (TASK.md time window).
  * Data completeness: a station-day is "observed" if >= 90 % of its 1440 minutes were recorded.
    Strict rule (TASK.md: skip the event if observations are missing): every day in the event
    window is observed. A lenient flag (>= 80 % of window days observed) is also written.
  * Agriculture connections are dropped (owner decision); Offline stations are kept within their
    From-To dates.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
BUFFERS_KM = [2.5, 5, 10, 20]
SEARCH_KM = 30.0
RECUR_MIN = 3
MIN_KM2 = 1.0
PAD_DAYS = 3
OBS_FRAC = 0.9
LENIENT_FRAC = 0.8
KM_PER_DEG = 111.195

log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log_lines.append(s)


def station_grid(s, res):
    """Station-centred grid (same resolution as GFD) covering +-SEARCH_KM."""
    coslat = np.cos(np.radians(s.lat))
    dlat = SEARCH_KM / KM_PER_DEG
    dlon = dlat / coslat
    ny, nx = int(np.ceil(2 * dlat / res)), int(np.ceil(2 * dlon / res))
    tr = from_origin(s.lon - dlon, s.lat + dlat, res, res)
    xs = tr.c + res * (np.arange(nx) + 0.5)
    ys = tr.f - res * (np.arange(ny) + 0.5)
    d = np.hypot((xs[None, :] - s.lon) * KM_PER_DEG * coslat, (ys[:, None] - s.lat) * KM_PER_DEG)
    px_km2 = res * res * KM_PER_DEG**2 * coslat
    return tr, (ny, nx), d, px_km2, dlat, dlon


def metrics(fl, d, px_km2, tag):
    rec = {f"min_dist_km_{tag}": float(d[fl].min()) if fl.any() else np.nan}
    for r in BUFFERS_KM:
        inb = d <= r
        rec[f"flood_km2_{r:g}km_{tag}"] = float(fl[inb].sum() * px_km2)
        rec[f"flood_frac_{r:g}km_{tag}"] = float(fl[inb].mean())
    return rec


def main():
    loc = pd.read_csv(ROOT / "data/locations.csv", parse_dates=["from_date", "to_date"])
    log(f"locations.csv: {len(loc)} rows, {loc.location.nunique()} unique names")
    loc = loc[loc.in_voltage_data & (loc.connection_type != "Agriculture")].copy()
    log(f"with voltage data, excluding Agriculture: {len(loc)} rows")

    qc = pd.read_csv(ROOT / "data/gfd/gfd_qcdatabase.csv", usecols=lambda c: c != "geometry")
    qc["Began"] = pd.to_datetime(qc.Began, format="%m/%d/%Y")
    qc["Ended"] = pd.to_datetime(qc.Ended, format="%m/%d/%Y")
    qc = qc.set_index("ID")

    daily = pd.read_csv(ROOT / "data/esmi_daily.csv.gz", usecols=["location", "date", "rec_min"],
                        parse_dates=["date"])
    daily["observed"] = daily.rec_min >= OBS_FRAC * 1440
    obs = {k: g.set_index("date").observed for k, g in daily.groupby("location")}

    tifs = sorted((ROOT / "data/gfd/tif").glob("DFO_*.tif"))
    log(f"{len(tifs)} GFD footprints")

    # Pass 1: resample each event's flood mask onto each nearby station's grid.
    stack = {}   # location -> {event_id: bool array}
    res = None
    for tif in tifs:
        eid = int(tif.name.split("_")[1])
        with rasterio.open(tif) as src:
            names = list(src.descriptions)
            if res is None:
                res = src.res[0]
                log(f"band names: {names}; crs {src.crs.to_string()}; res {src.res}")
            b_fl = names.index("flooded") + 1
            b_pw = names.index("jrc_perm_water") + 1
            L, B, R, T = src.bounds
            pad = SEARCH_KM / KM_PER_DEG
            cl = np.cos(np.radians(loc.lat))
            near = loc[(loc.lat > B - pad) & (loc.lat < T + pad) &
                       (loc.lon > L - pad / cl) & (loc.lon < R + pad / cl)]
            n = 0
            for _, s in near.iterrows():
                tr, shape, d, px, dlat, dlon = station_grid(s, res)
                win = from_bounds(s.lon - dlon - 2 * res, s.lat - dlat - 2 * res,
                                  s.lon + dlon + 2 * res, s.lat + dlat + 2 * res,
                                  src.transform).round_offsets().round_lengths()
                fl = src.read(b_fl, window=win, boundless=True, fill_value=0)
                pw = src.read(b_pw, window=win, boundless=True, fill_value=0)
                srcarr = ((fl == 1) & (pw != 1)).astype(np.uint8)
                if not srcarr.any():
                    continue
                dst = np.zeros(shape, np.uint8)
                reproject(srcarr, dst, src_transform=src.window_transform(win), src_crs=src.crs,
                          dst_transform=tr, dst_crs=src.crs, resampling=Resampling.nearest)
                if dst.any():
                    stack.setdefault(s.location, {})[eid] = dst.astype(bool)
                    n += 1
        log(f"  {tif.name}: {len(near)} stations in bbox, {n} with flooding within {SEARCH_KM:g} km")

    # Pass 2: recurrence mask and per-event metrics.
    rows = []
    sidx = loc.set_index("location")
    for name, evs in stack.items():
        s = sidx.loc[name]
        s = s if isinstance(s, pd.Series) else s.iloc[0]
        s = s.copy(); s["location"] = name
        _, _, d, px, _, _ = station_grid(s, res)
        recur = np.sum(list(evs.values()), axis=0) >= RECUR_MIN
        for eid, fl in evs.items():
            ev = qc.loc[eid]
            rec = dict(event_id=eid, location=name)
            rec.update(metrics(fl, d, px, "raw"))
            rec.update(metrics(fl & ~recur, d, px, "masked"))
            rec["recurrent_km2_20km"] = float((recur & (d <= 20)).sum() * px)
            rec.update(
                category=s.category, area_type=s.area_type, connection_type=s.connection_type,
                precision=s.precision, lat=s.lat, lon=s.lon,
                esmi_from=s.from_date, esmi_to=s.to_date,
                country=ev.Country, began=ev.Began, ended=ev.Ended,
                main_cause=ev.MainCause, severity=ev.Severity)
            rows.append(rec)

    es = pd.DataFrame(rows)
    es["win_start"] = es.began - pd.Timedelta(days=PAD_DAYS)
    es["win_end"] = es.ended + pd.Timedelta(days=PAD_DAYS)
    es["affected"] = es["flood_km2_20km_masked"] >= MIN_KM2
    es["affected_raw"] = es["min_dist_km_raw"] <= 20
    es["in_coverage"] = (es.esmi_from <= es.win_start) & (es.esmi_to >= es.win_end)
    es["overlaps_coverage"] = (es.esmi_from <= es.ended) & (es.esmi_to >= es.began)

    def cov(r):
        days = pd.date_range(r.win_start, r.win_end)
        o = obs.get(r.location)
        if o is None:
            return 0, len(days)
        return int(o.reindex(days, fill_value=False).sum()), len(days)
    c = es.apply(cov, axis=1, result_type="expand")
    es["obs_days"], es["win_days"] = c[0], c[1]
    es["obs_frac"] = es.obs_days / es.win_days
    es["complete_strict"] = es.obs_days == es.win_days
    es["complete_lenient"] = es.obs_frac >= LENIENT_FRAC
    es["keep"] = es.affected & es.in_coverage & es.complete_strict
    es["keep_lenient"] = es.affected & es.overlaps_coverage & es.complete_lenient
    es["keep_raw"] = es.affected_raw & es.in_coverage & es.complete_strict
    es["needs_geocode_fix"] = es.affected & (es.precision != "locality")
    es = es.sort_values(["event_id", "min_dist_km_masked"])
    es.to_csv(ROOT / "data/flood_event_stations.csv", index=False, float_format="%.4g")

    g = es.groupby("event_id")
    ev = pd.DataFrame({
        "n_affected": g.affected.sum(),
        "n_affected_in_coverage": g.apply(lambda x: (x.affected & x.overlaps_coverage).sum()),
        "n_keep_strict": g.keep.sum(), "n_keep_lenient": g.keep_lenient.sum(),
        "n_keep_raw_rule": g.keep_raw.sum(),
        "n_keep_needs_geocode_fix": g.apply(lambda x: (x.keep & x.needs_geocode_fix).sum()),
    })
    ids = [int(t.name.split("_")[1]) for t in tifs]
    meta = qc.loc[ids, ["Country", "Began", "Ended", "MainCause", "Severity"]]
    meta.columns = ["country", "began", "ended", "main_cause", "severity"]
    ev = meta.join(ev).fillna(0).rename_axis("event_id").reset_index()
    for col in [c for c in ev.columns if c.startswith("n_")]:
        ev[col] = ev[col].astype(int)
    ev["used"] = ev.n_keep_strict > 0
    ev.to_csv(ROOT / "data/flood_events.csv", index=False)

    log(f"\nRules: masked flooding >= {MIN_KM2} km2 within 20 km; recurrent = flooded in "
        f">= {RECUR_MIN} events; strict completeness over Began-{PAD_DAYS}d..Ended+{PAD_DAYS}d")
    log("\nPer-event counts:")
    log(ev.to_string(index=False))
    for k, lab in [("keep", "primary (masked, strict)"),
                   ("keep_lenient", "masked, lenient completeness"),
                   ("keep_raw", "raw 20 km rule, strict")]:
        sel = es[es[k]]
        log(f"{lab}: {sel.event_id.nunique()} events, {len(sel)} station-events, "
            f"{sel.location.nunique()} stations")
    fix = es[es.keep & es.needs_geocode_fix].drop_duplicates("location")
    log(f"\nkept stations not geocoded to locality (hand-fix candidates): {len(fix)}")
    log(fix[["location", "precision", "lat", "lon", "event_id", "min_dist_km_masked",
             "flood_km2_20km_masked"]].to_string(index=False))
    (ROOT / "outputs/04_flood_matching_log.txt").write_text("\n".join(log_lines) + "\n")

    plot_map(es, tifs)


def plot_map(es, tifs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    loc = pd.read_csv(ROOT / "data/locations.csv")
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.scatter(loc.lon, loc.lat, s=4, c="#bbbbbb", label="ESMI station", zorder=2)
    for tif in tifs:
        with rasterio.open(tif) as src:
            f = max(1, int(max(src.width, src.height) / 1500))
            names = list(src.descriptions)
            a = src.read(names.index("flooded") + 1, out_shape=(src.height // f, src.width // f))
            L, B, R, T = src.bounds
        ax.imshow(np.ma.masked_where(a != 1, a), extent=(L, R, B, T), origin="upper",
                  cmap=ListedColormap(["#2a6fdb"]), alpha=0.7, zorder=1, interpolation="nearest")
    r = es[es.affected_raw & es.in_coverage & ~es.keep]
    ax.scatter(r.lon, r.lat, s=18, facecolor="none", edgecolor="#d62728", lw=1,
               label="matched only by raw 20 km rule / incomplete data", zorder=3)
    kk = es[es.keep]
    ax.scatter(kk.lon, kk.lat, s=18, c="#d62728", label="kept (masked rule, complete data)", zorder=4)
    ax.set_xlim(66, 98); ax.set_ylim(6, 37); ax.set_aspect("equal")
    ax.set_xlabel("Longitude (°E)"); ax.set_ylabel("Latitude (°N)")
    ax.set_title("GFD flood footprints 2014–2018 (blue) and matched ESMI stations")
    ax.legend(loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(ROOT / "outputs/figures/04_flood_events_map.png", dpi=150)


if __name__ == "__main__":
    main()
