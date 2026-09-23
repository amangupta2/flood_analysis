# Data dictionary

Items marked **TODO** need input from the project owner. Everything else was checked directly against the files.

## Rainfall: `RF25_ind{YEAR}_rfp25.nc` (2014–2018)

| Field | Type | Meaning |
|---|---|---|
| `TIME` | double, 365/366 per file (unlimited dim) | Day. Units `days since 1900-12-31` |
| `LATITUDE` | double, 129 | 6.5–38.5°N, 0.25° step, ascending |
| `LONGITUDE` | double, 135 | 66.5–100°E, 0.25° step |
| `RAINFALL(TIME, LATITUDE, LONGITUDE)` | float | Daily rainfall, mm. `-999` = missing/ocean (set as `_FillValue` and `missing_value`, so xarray masks it automatically) |

- Source: IMD 0.25° gridded rainfall, converted from GrADS `ind{YEAR}_rfp25.grd` to NetCDF with Ferret.
- Accumulation window: IMD daily values are normally 24 h totals ending 08:30 IST on the labelled date. **TODO:** confirm for this product.

## Voltage: `ESMI minute-wise voltage data <period>.csv` (2014–2018)

Source: Prayas ESMI (Electricity Supply Monitoring Initiative), with residential-supply voltage monitors.

| Column | Meaning |
|---|---|
| `Location name` | Free text: `"<locality>-<city>"` or `"<locality>- <city>"`, sometimes with a suffix like ` [Offline]` |
| `Date` | **DD-MM-YYYY** |
| `Hour` | 0–23, local time (**TODO:** confirm IST) |
| `Min 0` … `Min 59` | Voltage (V) for each minute of that hour |

- Wide format: one row per location per hour, 63 columns. A complete row always has 63 fields.
- Filenames contain spaces and cover irregular periods (e.g. `2016 Jan-June`, `2017 Sept-Dec`). Quote paths when using them.
- Files are 15–230 MB each (~1.5 GB total). Read them in chunks or with explicit dtypes, inside a Slurm job.
- Rows are not globally sorted by date (e.g. the 2014 file starts at 31-10-2014).
- There are no lat/lon values. Mapping locations to the rainfall grid needs a lookup table (see below).

### Observed values (2014 file only; other files not yet profiled)
- 62 distinct locations.
- No blank minute values.
- About 13% of minute values are exactly `0`.
- The other values range from 99 to 350 V. Most fall around 230–260 V.

### Value semantics (**TODO**)
- `0`: assumed to mean no supply (power cut). **TODO:** confirm, and say whether it could also mean monitor failure.
- How to tell monitor downtime from a power cut: missing rows? **TODO**
- Low / high voltage thresholds (e.g. <200 V, >270 V): **TODO**
- Meaning of `[Offline]` and whether those locations should be kept: **TODO**

### Truncated files
Five CSVs are **incomplete downloads**. Each has a size that is an exact multiple of 4096 bytes, the same 23:01 mtime, and a final row cut off mid-line with no trailing newline:
`2016 Jan-June`, `2016 July-Dec`, `2017 May-Aug`, `2017 Sept-Dec`, `2018 June-Aug`.
When reading them, drop the partial last row (require 63 fields). Don't read gaps late in these periods as real outages or monitor downtime, since the data may simply be cut off. The real fix is to re-download these files.

## Location coordinates (**TODO**)
Planned file: `data/locations.csv` with columns `location_name, city, state, lat, lon, source`.
- Source of coordinates: supplied by project owner, ESMI metadata, or geocoded? **TODO**
- Required accuracy (city centroid vs. locality): **TODO**
