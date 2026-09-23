# Task

Fill in the **TODO**s. Short answers are fine. Delete any section that doesn't apply.

## Research question
Do floods and heavy rainfall reduce the quality of residential electricity supply in India, and by how much?
**TODO:** refine (e.g. specific regions, the monsoon season only, particular flood events).

## Definitions
- **Heavy rain / flood event:** **TODO**. Options:
  - fixed threshold (IMD: heavy ≥ 64.5 mm/day, very heavy ≥ 115.6, extremely heavy ≥ 204.5)
  - location-specific percentile (e.g. above the 95th / 99th)
  - multi-day totals
  - external list of known flood events
- **Spatial match:** the single grid cell containing the location, or an average over nearby cells (radius?). **TODO**
- **Outcomes** (pick any): **TODO**
  - outage minutes/hours per day
  - number of outages per day
  - outage duration and time to restore supply
  - minutes of low / high voltage
  - voltage variability
- **Time window after an event:** same day, lags of 1–N days? **TODO**

## Method
**TODO:** descriptive comparisons (event vs. non-event days), panel regression with location and date fixed effects, event study, other.
Controls or confounders to handle (season, day of week, location trends): **TODO**

## Deliverables
**TODO**. For example:
- [ ] Cleaned long-format voltage dataset (Parquet)
- [ ] Location → coordinates → grid-cell lookup
- [ ] Daily location-level panel with rainfall + supply metrics
- [ ] Figures
- [ ] Analysis notebook or scripts
- [ ] Written summary

## Tooling preferences
- Language / libraries: **TODO** (e.g. Python with xarray, pandas/polars, statsmodels)
- Environment: **TODO** (venv location under `$SCRATCH` or `$GROUP_HOME`; the Sherlock policy is to avoid Conda)
- Output location: **TODO** (e.g. `outputs/` in this directory)
