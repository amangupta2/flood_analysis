"""Build the daily station panel: outages + IMD rain + AIFS rain at leads 1-5 + flood-event flags.

One row per (station, IMD day) within the station's ESMI coverage.

Time alignment (all in UTC; IST = UTC+5:30)
  * IMD day D = 24 h ending 08:30 IST = 03 UTC on D, i.e. 03 UTC D-1 .. 03 UTC D.
  * ESMI day D = calendar day in IST = 18:30 UTC D-1 .. 18:30 UTC D. The IMD day therefore
    overlaps the ESMI day by 15.5 h and leads it by 8.5 h; lags 0-2 d in the model absorb this.
  * AIFS lead L (1..5) for IMD day D = forecast initialised 00 UTC on D-L. The window is
    hours 24(L-1)+3 .. 24L+3 after init. Steps are 6-hourly accumulations ending at 6,12,...,120 h;
    the two steps straddling 03 UTC are split in half (uniform rain within a step).
      tp_day(L) = 0.5*s(24L-18) + s(24L-12) + s(24L-6) + s(24L) + 0.5*s(24L+6)
    For L = 5 the last step (126 h) does not exist; the 21 available hours are scaled by 24/21.
  * 48 h accumulation for IMD days D-1 and D from the same init: tp48(L) = tp_day(L) + tp_day(L-1),
    so it exists for L = 2..5 only (lead 1 would need hours before init).
  * AIFS is metres -> x1000 for mm (checked in scripts/05_check_aifs_units.py).

Spatial match
  * Centre cell = nearest IMD cell with data (imd_valid_i/j in data/locations.csv). IMD points
    coincide with AIFS points, so the same cells are used for both.
  * Predictors: centre cell, 3x3 mean and 3x3 max (IMD-valid cells only, for both sources).

Outcome helpers (the modelling script picks the final definition)
  * observed = >= 90 % of the day's minutes recorded; outage metrics on other days set to NaN.
  * out_p90 = station's 90th percentile of daily outage minutes over observed non-event days;
    disrupt = out_min > out_p90.
  * out_base = median of out_min over observed non-event days with the same station, month and
    day of week; out_excess = out_min - out_base.
  * Event flags come from kept station-events in data/flood_event_stations.csv.

Output: data/panel_daily.parquet (+ outputs/06_panel_summary.txt)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
OBS_FRAC = 0.9
LEADS = [1, 2, 3, 4, 5]
AIFS_LAT0, AIFS_LON0, RES = 40.0, 65.0, 0.25
out = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); out.append(s)


def neighbourhood(ii, jj, valid):
    """3x3 index lists (IMD-valid cells only) around each station centre."""
    nb = []
    for i, j in zip(ii, jj):
        cells = [(i + di, j + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)
                 if 0 <= i + di < valid.shape[0] and 0 <= j + dj < valid.shape[1]
                 and valid[i + di, j + dj]]
        nb.append(cells)
    return nb


def main():
    loc = pd.read_csv(ROOT / "data/locations.csv", parse_dates=["from_date", "to_date"])
    loc = loc[loc.in_voltage_data & (loc.connection_type != "Agriculture")].reset_index(drop=True)
    log(f"stations: {len(loc)}")

    # ---------------- IMD ----------------
    imd = xr.concat([xr.open_dataset(f).RAINFALL.load()
                     for f in sorted(ROOT.glob("RF25_ind201[4-8]_rfp25.nc"))], dim="TIME")
    imd_lat, imd_lon = imd.LATITUDE.values, imd.LONGITUDE.values
    days = pd.DatetimeIndex(imd.TIME.values).normalize()
    R = imd.values.astype(np.float32)                       # (time, lat, lon), NaN = no data
    valid = np.isfinite(R).any(axis=0)
    ii, jj = loc.imd_valid_i.values.astype(int), loc.imd_valid_j.values.astype(int)
    nb = neighbourhood(ii, jj, valid)
    log(f"IMD: {len(days)} days {days[0].date()}..{days[-1].date()}; 3x3 valid cells per station: "
        f"min {min(map(len, nb))}, median {int(np.median(list(map(len, nb))))}")

    def extract(A):
        """A (time, lat, lon) on the IMD grid -> centre, 3x3 mean, 3x3 max; each (time, station)."""
        c = A[:, ii, jj]
        m = np.stack([np.nanmean(A[:, [a for a, _ in n], [b for _, b in n]], axis=1) for n in nb], 1)
        x = np.stack([np.nanmax(A[:, [a for a, _ in n], [b for _, b in n]], axis=1) for n in nb], 1)
        return c, m, x

    cols = {}
    c, m, x = extract(R)
    cols["imd_c"], cols["imd_m3"], cols["imd_x3"] = c, m, x

    # ---------------- AIFS ----------------
    # Map IMD grid to AIFS-subset indices (AIFS subset lat 40 -> 5 descending, lon 65 -> 100).
    ai = np.rint((AIFS_LAT0 - imd_lat) / RES).astype(int)
    aj = np.rint((imd_lon - AIFS_LON0) / RES).astype(int)
    inits = pd.date_range(days[0] - pd.Timedelta(days=5), days[-1])
    TP = np.full((len(inits), 20, len(imd_lat), len(imd_lon)), np.nan, np.float32)
    missing, checked = [], False
    for k, t in enumerate(inits):
        f = ROOT / f"data/aifs_india/aifs_era5_india_tp_leadtime_120hrs_{t:%Y%m%d}.nc"
        if not f.exists():
            missing.append(t.date()); continue
        with xr.open_dataset(f, decode_times=False) as ds:
            if not checked:
                assert np.allclose(ds.lat.values[ai], imd_lat) and np.allclose(ds.lon.values[aj], imd_lon)
                assert list(ds.leadtime.values) == list(range(6, 121, 6))
                checked = True
            TP[k] = ds.total_precipitation.values[:, ai][:, :, aj] * 1000.0     # m -> mm
    TP[:, :, ~valid] = np.nan
    log(f"AIFS: {len(inits)} init dates needed, {len(missing)} missing: {missing}")

    step = lambda h: h // 6 - 1                              # lead hour -> step index
    def day_total(L):
        """AIFS rain for IMD day D at lead L, as array (day, lat, lon)."""
        k = (days - pd.Timedelta(days=L) - inits[0]).days.values
        S = lambda h: TP[k, step(h)]                        # (day, lat, lon)
        h0 = 24 * L
        tot = 0.5 * S(h0 - 18) + S(h0 - 12) + S(h0 - 6) + S(h0)
        if L < 5:
            tot = tot + 0.5 * S(h0 + 6)
        else:
            tot = tot * 24.0 / 21.0
        return tot

    daytot = {L: day_total(L) for L in LEADS}
    for L in LEADS:
        c, m, x = extract(daytot[L])
        cols[f"aifs_l{L}_c"], cols[f"aifs_l{L}_m3"], cols[f"aifs_l{L}_x3"] = c, m, x
    # 48 h from one init: day D at lead L + day D-1 at lead L-1 (same init D-L).
    for L in LEADS[1:]:
        prev = np.roll(daytot[L - 1], 1, axis=0); prev[0] = np.nan
        c, m, x = extract(daytot[L] + prev)
        cols[f"aifs48_l{L}_c"], cols[f"aifs48_l{L}_m3"], cols[f"aifs48_l{L}_x3"] = c, m, x
    for k in ["c", "m3", "x3"]:
        a = cols[f"imd_{k}"]
        p = np.roll(a, 1, axis=0); p[0] = np.nan
        cols[f"imd48_{k}"] = a + p

    # --------------- assemble ---------------
    nt, ns = len(days), len(loc)
    panel = pd.DataFrame({"location": np.tile(loc.location.values, nt),
                          "date": np.repeat(days.values, ns)})
    for k, v in cols.items():
        panel[k] = v.reshape(-1).astype(np.float32)

    daily = pd.read_csv(ROOT / "data/esmi_daily.csv.gz", parse_dates=["date"])
    panel = panel.merge(daily, on=["location", "date"], how="left")
    meta = loc[["location", "category", "area_type", "connection_type", "state", "district",
                "precision", "lat", "lon", "from_date", "to_date"]]
    panel = panel.merge(meta, on="location", how="left")
    panel = panel[(panel.date >= panel.from_date) & (panel.date <= panel.to_date)].copy()
    panel["rec_min"] = panel.rec_min.fillna(0)
    panel["observed"] = panel.rec_min >= OBS_FRAC * 1440
    for c in ["out_min", "zero_min", "supply_min", "mean_supply_v"]:
        panel.loc[~panel.observed, c] = np.nan
    panel["out_frac"] = panel.out_min / panel.rec_min

    # --------------- event flags ---------------
    es = pd.read_csv(ROOT / "data/flood_event_stations.csv",
                     parse_dates=["began", "ended", "win_start", "win_end"])
    kept = es[es.keep]
    ev_rows = []
    for _, r in kept.iterrows():
        for d in pd.date_range(r.win_start, r.win_end):
            ev_rows.append((r.location, d, r.event_id, (d - r.began).days,
                            r.began <= d <= r.ended))
    ev = pd.DataFrame(ev_rows, columns=["location", "date", "event_id", "rel_day", "in_event"])
    ev = ev.sort_values(["location", "date", "event_id"])
    evg = ev.groupby(["location", "date"]).agg(
        event_ids=("event_id", lambda s: ";".join(map(str, s))),
        event_id=("event_id", "first"), rel_day=("rel_day", "first"),
        in_event=("in_event", "any")).reset_index()
    panel = panel.merge(evg, on=["location", "date"], how="left")
    panel["in_window"] = panel.event_id.notna()
    panel["in_event"] = panel.in_event.fillna(False).astype(bool)
    # Any flooding match at all (raw rule, incl. dropped ones) -> excluded from the baseline too.
    anyev = es[es.affected_raw]
    near = set()
    for _, r in anyev.iterrows():
        for d in pd.date_range(r.win_start, r.win_end):
            near.add((r.location, d))
    panel["any_flood_nearby"] = [(a, b) in near for a, b in zip(panel.location, panel.date)]

    # --------------- outcomes ---------------
    base = panel.observed & ~panel.any_flood_nearby
    p90 = panel[base].groupby("location").out_min.quantile(0.9).rename("out_p90")
    panel = panel.merge(p90, on="location", how="left")
    panel["disrupt"] = np.where(panel.observed, (panel.out_min > panel.out_p90).astype(float), np.nan)
    panel["month"], panel["dow"] = panel.date.dt.month, panel.date.dt.dayofweek
    bm = (panel[base].groupby(["location", "month", "dow"]).out_min.median().rename("out_base"))
    panel = panel.merge(bm, on=["location", "month", "dow"], how="left")
    panel["out_excess"] = panel.out_min - panel.out_base
    panel = panel.sort_values(["location", "date"]).reset_index(drop=True)
    panel["out_min_lag1"] = panel.groupby("location").out_min.shift(1)
    panel["disrupt_lag1"] = panel.groupby("location").disrupt.shift(1)

    panel.to_parquet(ROOT / "data/panel_daily.parquet", index=False)
    log(f"\npanel: {len(panel):,} station-days, {panel.location.nunique()} stations, "
        f"{panel.observed.mean():.1%} observed")
    log(f"event-window station-days (kept events): {panel.in_window.sum():,}; "
        f"event days: {panel.in_event.sum():,}")
    log(f"stations with out_p90 == 0 (disrupt = any outage): {(p90 == 0).sum()} of {len(p90)}")
    log(f"disrupt base rate: all {panel.disrupt.mean():.3f}, event days "
        f"{panel.loc[panel.in_event, 'disrupt'].mean():.3f}")
    log("\nmean rain (mm/day), JJAS observed days:")
    jj_ = panel[panel.month.between(6, 9)]
    log(jj_[["imd_c"] + [f"aifs_l{L}_c" for L in LEADS]].mean().round(2).to_string())
    log("\ncorrelation with IMD (centre cell), JJAS:")
    log(jj_[[f"aifs_l{L}_c" for L in LEADS]].corrwith(jj_.imd_c).round(3).to_string())
    (ROOT / "outputs/06_panel_summary.txt").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
