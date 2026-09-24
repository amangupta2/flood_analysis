# Data dictionary

Items marked **TODO** need input from the project owner. Everything else was checked directly against the files.

Time zones: IMD rainfall and ESMI voltage are in **IST (UTC+5:30)**; AIFS forecasts are in **UTC**. India ≈ 5–40°N, 65–100°E.

## Rainfall: `RF25_ind{YEAR}_rfp25.nc` (2014–2018)

| Field | Type | Meaning |
|---|---|---|
| `TIME` | double, 365/366 per file (unlimited dim) | Day. Units `days since 1900-12-31` |
| `LATITUDE` | double, 129 | 6.5–38.5°N, 0.25° step, ascending |
| `LONGITUDE` | double, 135 | 66.5–100°E, 0.25° step |
| `RAINFALL(TIME, LATITUDE, LONGITUDE)` | float | Daily rainfall, mm. `-999` = missing/ocean (set as `_FillValue` and `missing_value`, so xarray masks it automatically) |

- Source: IMD 0.25° gridded rainfall (Pai et al., 2014), converted from GrADS `ind{YEAR}_rfp25.grd` to NetCDF with Ferret.
- Accumulation window: IMD daily values are normally 24 h totals ending 08:30 IST (= 03:00 UTC) on the labelled date. Confirmed by the owner (2026-09-23).

## Forecasts: AIFS (`/scratch/users/ag4680/forecasts/aifs/*.nc`, read-only)

**Never modify these files.** Write all derived subsets under this project directory. Ignore the subdirectories (`aifs/`, `ifs/`, `temp_files/`).

- Files are named `aifs_era5_0p25_leadtime_120hrs_YYYYMMDD.nc`, **one file per initialisation date**, 2014-01-01 to 2018-12-31. About 1,818 files exist out of 1,826 days, so a few init dates are missing. Total ~8.5 TB.
- Dimensions: `leadtime` = 20 (6-hourly steps out to 120 h = 1–5 day leads), `lat` = 721, `lon` = 1440 (global 0.25° grid, not identical to the IMD grid), `pres` = 3.
- Variables: 2 m temperature and dewpoint, 10 m winds, MSLP, `total_precipitation`, low/medium/high cloud cover, and u, v, T, q, z on 3 pressure levels.
- `total_precipitation` is the **6-hourly accumulation between consecutive steps** (not accumulated from init). It has no `units` attribute, but it is **metres**: over Indian land in July 2016, IMD daily mm / AIFS lead-1 daily sum has a median ratio of ~896 (i.e. AIFS ~12 % wetter than IMD, since 1000/896 ≈ 1.12), and values do not grow with lead time (`logs/aifs_units_check.log`, `scripts/05_check_aifs_units.py`). Multiply by 1000 for mm.
- Times are UTC. `time` = 0 `days since <init date> 00:00` and `leadtime` = 6, 12, …, 120 (hours), so **init is 00 UTC** and step k covers (k−6, k] h after init.
- Grid: lat 90 → −90 (descending), lon 0 → 359.75. The IMD points coincide exactly with AIFS points, so no regridding is needed.
- Missing init dates (8): 2014-08-03, 2014-08-04, 2014-09-05, 2015-12-05, 2015-12-06, 2016-07-25, 2016-07-26, 2016-08-17.
- India subsets (precipitation only, 5–40°N, 65–100°E, 141×141, 2.8 GB total): `data/aifs_india/aifs_era5_india_tp_leadtime_120hrs_YYYYMMDD.nc` (`scripts/03_subset_aifs_india.sbatch`).
- Matching to IMD days: the IMD day ending 03:00 UTC on day D spans 03 UTC D-1 to 03 UTC D. AIFS steps end at 00/06/12/18 UTC, so each IMD day needs the 06–12, 12–18 and 18–00 steps, plus half of the 00–06 steps on either side (assume uniform rain within a step).

## Voltage: `ESMI minute-wise voltage data <period>.csv` (2014–2018)

Source: Prayas ESMI (Electricity Supply Monitoring Initiative), with residential-supply voltage monitors. Public archive: https://dataverse.harvard.edu/dataverse/esmi

| Column | Meaning |
|---|---|
| `Location name` | Free text: `"<locality>-<city>"` or `"<locality>- <city>"`, sometimes with a suffix like ` [Offline]` |
| `Date` | **DD-MM-YYYY** |
| `Hour` | 0–23, local time (IST) |
| `Min 0` … `Min 59` | Voltage (V) for each minute of that hour |

- Wide format: one row per location per hour, 63 columns. A complete row always has 63 fields.
- Filenames contain spaces and cover irregular periods (e.g. `2016 Jan-June`, `2017 Sept-Dec`). Quote paths when using them.
- Files are 15–230 MB each (~1.5 GB total). Read them in chunks or with explicit dtypes, inside a Slurm job.
- Rows are not globally sorted by date (e.g. the 2014 file starts at 31-10-2014).
- There are no lat/lon values. Mapping locations to the rainfall grid needs a lookup table (see below).

### Observed values (2014 file only; full profile in `outputs/01_esmi_file_summary.csv` and `data/esmi_locations.csv`)
- 62 distinct locations.
- No blank minute values.
- About 13% of minute values are exactly `0`.
- The other values range from 99 to 350 V. Most fall around 230–260 V.

### Value semantics
- **Outage minute = voltage < 130 V.** This follows Verschuur & Balakrishnan (2024). The count of exact-`0` minutes is also kept, so the stricter "0 = no supply" definition can be tested. `0` may sometimes be monitor failure, but there is no way to tell, so it is treated as an outage (owner decision).
- How to tell monitor downtime from a power cut: missing rows = monitor downtime (no data). A day counts as observed if ≥ 90 % of its minutes are recorded.
- Voltage bands: outage < 130 V, low 130–200 V, high > 270 V (owner left this to Claude).
- `[Offline]` (177 of 528 metadata rows) most likely means the monitor was later decommissioned (only 1 of 177 runs to Dec 2018). Owner decision: keep these stations, using only data within their From–To dates.
- ESMI location categories: State Capital / District HQ (urban), Other Municipal Area (peri-urban), Gram Panchayat (rural). These come from `ESMI location information.csv` (below).

## Location metadata: `ESMI location information.csv`
From the same Dataverse dataset. 528 rows. Columns: `Location name, From date, To date, District, State, Category, Connection Type`. Dates are DD-MM-YYYY.
- Category: State Capital 105, District Headquarters 159, Other Municipal Area 65, Gram Panchayat 199.
- Connection Type: Domestic 433, Non Domestic 83, Agriculture 12. Owner decision: drop Agriculture (rostered farm-pump feeders). Main analysis = Domestic + Non Domestic; sensitivity check = Domestic only.
- No coordinates. District + state are used to constrain geocoding.

### Truncated files (fixed 2026-09-23)
Five CSVs were originally **incomplete downloads** (sizes an exact multiple of 4096 bytes, same 23:01 mtime, last row cut off mid-line): `2016 Jan-June`, `2016 July-Dec`, `2017 May-Aug`, `2017 Sept-Dec`, `2018 June-Aug`. The 2017 May–Aug and Sept–Dec files were missing ~70% of their content.
They were re-downloaded from Harvard Dataverse (doi:10.7910/DVN/CLLZZM; guestbook response submitted with the owner's approval; `scripts/00_redownload_esmi.sbatch`). All 10 CSVs now match the Dataverse `originalFileSize` byte for byte. The truncated copies are kept in `redownload/truncated_old/` and can be deleted.

## Flood events: Global Flood Database (`data/gfd/`)

- Source: Tellman et al. (2021), MODIS 250 m flood footprints for 913 events, 2000–2018. Public buckets: `gs://gfd_v3` (GeoTIFF). Event table: `data/gfd/gfd_qcdatabase.csv` (from github.com/cloudtostreet/MODIS_GlobalFloodDatabase).
- Each GeoTIFF (EPSG:4326, ~250 m) has bands `flooded` (0/1), `duration`, `clear_views`, `clear_perc`, `jrc_perm_water`, in that order (checked on read).
- **Caveat:** `flooded` includes seasonally wet river channels that JRC does not count as permanent water (e.g. the Brahmaputra at Guwahati, the Ganga). Stations near big rivers therefore "match" almost every regional event.
- Downloaded to `data/gfd/tif/`: all 15 India-primary events from 2015–2018, plus 11 events in neighbouring countries (Pakistan, Bangladesh, Myanmar, Sri Lanka) whose footprints may reach into India.
- Verschuur & Balakrishnan (2024) report 27 GFD events in India for 2015–2018, of which 15 overlap ESMI stations. They did not publish the list, so we rebuild it (see TASK.md). We emailed the authors. Verschuur replied (2026-09-23) that they did not take the work further because the data quality was poor, so no list or coordinates are coming.
- Only events that fall within the ESMI coverage period of an affected location are used.

## Location coordinates (**TODO**)
Planned file: `data/locations.csv` with columns `location_name, city, state, lat, lon, source`.
- ESMI publishes only state and district. Verschuur & Balakrishnan geocoded the locality names by hand, to a few hundred metres–1 km. The authors are not sharing theirs, so we geocode our own (`scripts/02_geocode_locations.py`).
- Required accuracy: locality level (needed for the 2.5–20 km flood buffers). City centroid is enough for the 0.25° rainfall match.
