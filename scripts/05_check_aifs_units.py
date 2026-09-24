"""Check AIFS total_precipitation units and step semantics against IMD rainfall (July 2016).

Questions (DATA.md TODOs):
  1. Is total_precipitation in metres? -> compare the India-mean daily total with IMD (mm).
  2. Is it a 6-hourly accumulation per step, or accumulated from init?
     -> if accumulated, values would grow monotonically with leadtime.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
imd = xr.open_dataset(ROOT / "RF25_ind2016_rfp25.nc").RAINFALL
days = pd.date_range("2016-07-02", "2016-07-31")
rows = []
for d in days:
    init = d - pd.Timedelta(days=1)
    f = ROOT / f"data/aifs_india/aifs_era5_india_tp_leadtime_120hrs_{init:%Y%m%d}.nc"
    if not f.exists():
        print(f"missing AIFS init {init:%Y-%m-%d}; skipped")
        continue
    ds = xr.open_dataset(f, decode_times=False)
    tp = ds.total_precipitation
    if not rows:
        m = tp.mean(("lat", "lon")).values
        print("India-mean tp by leadtime (raw units):", np.round(m, 6))
        print("monotonic non-decreasing (would mean accumulated from init)?",
              bool(np.all(np.diff(m) >= 0)))
    # Leads 6..120 h from 00 UTC init D-1. IMD day D = 03 UTC D-1 .. 03 UTC D.
    # Steps ending 06,12,18,24 h cover 00-24 UTC D-1; step ending 30 h covers 00-06 UTC D.
    # Uniform-rain split: half of the 00-06 (lead 6) step is outside the window, half of the 24-30 step inside.
    lt = list(ds.leadtime.values)
    s = lambda h: tp.isel(leadtime=lt.index(h))
    aifs_day = 0.5 * s(6) + s(12) + s(18) + s(24) + 0.5 * s(30)
    aifs_day = aifs_day.sortby("lat").sel(lat=imd.LATITUDE, lon=imd.LONGITUDE, method="nearest")
    obs = imd.sel(TIME=d.strftime("%Y-%m-%d")).squeeze()
    mask = np.isfinite(obs.values)
    a = aifs_day.values[mask]; o = obs.values[mask]
    rows.append(dict(date=d, imd_mean_mm=o.mean(), aifs_mean_raw=a.mean(),
                     ratio_mm_per_raw=o.mean() / a.mean(),
                     spatial_r=np.corrcoef(a, o)[0, 1]))
df = pd.DataFrame(rows)
print(df.round(5).to_string(index=False))
print("\nmedian IMD/AIFS ratio:", round(df.ratio_mm_per_raw.median(), 1),
      "(~1000 => AIFS is metres)")
print("mean spatial correlation, lead-1 day:", round(df.spatial_r.mean(), 3))
print("IMD grid check: AIFS lat/lon at IMD points match exactly:",
      bool(np.allclose(aifs_day.lat.values, imd.LATITUDE.values)
           and np.allclose(aifs_day.lon.values, imd.LONGITUDE.values)))
