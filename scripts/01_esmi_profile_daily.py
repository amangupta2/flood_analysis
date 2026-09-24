"""Step 1: profile the ESMI minute-wise voltage CSVs and build a daily outage panel.

Inputs : ESMI minute-wise voltage data *.csv  (wide: one row per location-hour, 60 minute columns)
Outputs: data/esmi_hourly.csv.gz           location x date x hour summary (deduplicated)
         data/esmi_daily.csv.gz            location x date: recorded minutes, outage minutes, ...
         data/esmi_locations.csv           one row per location: coverage period, days, outage stats
         outputs/01_esmi_file_summary.csv  one row per input file: rows, dropped rows, date range

Decisions (see docs/DATA.md):
- Outage minute = voltage < 130 V (Verschuur & Balakrishnan 2024 definition). We also keep the
  count of exact-zero minutes so the stricter "0 = no supply" definition can be used later.
- A minute value that is blank/non-numeric counts as "not recorded" (monitor data missing),
  NOT as an outage.
- Truncated downloads (file does not end in a newline): the partial last line is dropped.
- Location names are normalised: " [Offline]" suffix removed, "- " -> "-", whitespace trimmed.
  The raw name is kept for traceability.
- Outputs are gzipped CSV (written before pyarrow was added to the env; later steps use Parquet).
- Files overlap in time for some locations; duplicate (location, date, hour) rows are dropped,
  keeping the first occurrence.
"""
import glob
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = "/scratch/users/ag4680/flood_analysis"
OUTAGE_V = 130
MIN_COLS = [f"Min {i}" for i in range(60)]
NFIELDS = 63

os.chdir(ROOT)
os.makedirs("data", exist_ok=True)
os.makedirs("outputs", exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def norm_name(s):
    s = re.sub(r"\s*\[offline\]\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def file_is_truncated(path):
    with open(path, "rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) != b"\n"


hourly_parts, file_rows = [], []
for path in sorted(glob.glob("ESMI minute-wise voltage data *.csv")):
    t0 = time.time()
    truncated = file_is_truncated(path)
    # Truncated files end with a partial line. With keep_default_na=False pandas pads its missing
    # fields with "" (indistinguishable from a blank minute), so drop that final row explicitly.
    n_total = sum(1 for _ in open(path, "rb")) - 1  # data rows (header excluded)
    n_read = n_kept = 0
    for chunk in pd.read_csv(path, dtype=str, chunksize=500_000, keep_default_na=False):
        n_read += len(chunk)
        if truncated and n_read == n_total:
            chunk = chunk.iloc[:-1]
        n_kept += len(chunk)
        v = chunk[MIN_COLS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype="float32")
        rec = ~np.isnan(v)
        hourly_parts.append(pd.DataFrame({
            "location_raw": chunk["Location name"].values,
            "date": pd.to_datetime(chunk["Date"].values, format="%d-%m-%Y", errors="coerce"),
            "hour": pd.to_numeric(pd.Series(chunk["Hour"].values), errors="coerce").astype("float32"),
            "n_rec": rec.sum(1).astype("int16"),
            "n_out": ((v < OUTAGE_V) & rec).sum(1).astype("int16"),
            "n_zero": ((v == 0) & rec).sum(1).astype("int16"),
            "v_sum": np.where(rec & (v >= OUTAGE_V), v, 0).sum(1),  # for mean supply voltage
            "src": os.path.basename(path),
        }))
    last = hourly_parts[-1]
    file_rows.append({"file": path, "truncated": truncated, "rows_read": n_read,
                      "rows_kept": n_kept, "rows_dropped": n_read - n_kept,
                      "sec": round(time.time() - t0, 1)})
    log(f"{path}: read {n_read}, kept {n_kept}, truncated={truncated}")

hourly = pd.concat(hourly_parts, ignore_index=True)
del hourly_parts
bad = hourly["date"].isna() | hourly["hour"].isna()
log(f"rows with unparseable date/hour dropped: {int(bad.sum())}")
hourly = hourly[~bad]
hourly["location"] = hourly["location_raw"].map(norm_name)

# per-file date range
fs = pd.DataFrame(file_rows)
rng = hourly.groupby("src")["date"].agg(["min", "max"]).rename(columns={"min": "date_min", "max": "date_max"})
fs["src"] = fs["file"].map(os.path.basename)
fs = fs.merge(rng, left_on="src", right_index=True, how="left").drop(columns="src")
fs["n_locations"] = fs["file"].map(lambda f: hourly.loc[hourly.src == os.path.basename(f), "location"].nunique())
fs.to_csv("outputs/01_esmi_file_summary.csv", index=False)
print(fs.to_string())

n0 = len(hourly)
hourly = hourly.drop_duplicates(["location", "date", "hour"], keep="first")
log(f"duplicate location-date-hour rows dropped: {n0 - len(hourly)}")
hourly.to_csv("data/esmi_hourly.csv.gz", index=False)

daily = hourly.groupby(["location", "date"]).agg(
    n_hours=("hour", "size"), rec_min=("n_rec", "sum"), out_min=("n_out", "sum"),
    zero_min=("n_zero", "sum"), v_sum=("v_sum", "sum")).reset_index()
daily["supply_min"] = daily["rec_min"] - daily["out_min"]
daily["mean_supply_v"] = (daily["v_sum"] / daily["supply_min"].where(daily["supply_min"] > 0)).astype("float32")
daily = daily.drop(columns="v_sum")
daily.to_csv("data/esmi_daily.csv.gz", index=False)
log(f"daily panel: {len(daily)} location-days, {daily.location.nunique()} locations")

raw_names = hourly.groupby("location")["location_raw"].agg(lambda s: " | ".join(sorted(set(s))))
full = daily[daily.rec_min >= 1440 * 0.9]  # "complete" days: >=90% of minutes recorded
locs = daily.groupby("location").agg(
    first_date=("date", "min"), last_date=("date", "max"), n_days=("date", "size"),
    mean_out_min=("out_min", "mean")).join(
    full.groupby("location").size().rename("n_complete_days")).join(raw_names.rename("raw_names"))
locs["n_complete_days"] = locs["n_complete_days"].fillna(0).astype(int)
locs["city"] = locs.index.str.split("-").str[-1].str.strip()
locs.to_csv("data/esmi_locations.csv")
log(f"wrote data/esmi_locations.csv ({len(locs)} locations)")

print("\nOverall date range:", daily.date.min().date(), "to", daily.date.max().date())
print("Locations with >=180 complete days:", int((locs.n_complete_days >= 180).sum()))
print("\nlocation-days per year:\n", daily.groupby(daily.date.dt.year).size().to_string())
print("\noutage-minute distribution (complete days):\n", full.out_min.describe().to_string())
