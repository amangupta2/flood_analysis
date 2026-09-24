# Task

In this task we will be:
1) Comparing the AIFS forecasts with ground based data in .csv files and and the gridded IMD rain gauge data in RF25_ind201*.nc files, and assessing How far in advance can raw AIFS forecasts identify electricity-service disruption during Indian floods?
2) The flood case studies are in the following study: https://egusphere.copernicus.org/preprints/2024/egusphere-2024-3176/
3) Here is a compact experiment design:
- Use the 15 flood events already matched to ESMI locations in the existing India outage study.
- Run frozen AIFS hindcasts at 1–5-day leads.
- At each ESMI location, calculate nearby 24- or 48-hour accumulated forecast precipitation.
- Define the outcome as either:
	outage minutes above that station’s 90th percentile, or
	excess outage minutes relative to its normal local baseline.

- Fit a simple logistic or mixed-effects model.
- Test with leave-one-flood-event-out cross-validation, so the model must predict a genuinely unseen flood.
- Compare against climatology, outage persistence and, ideally, IFS precipitation forecasts.
- IMERG is unnecessary. IMD rainfall could be used only as an observational “perfect-rainfall” benchmark: how much outage predictability is lost when observed rainfall is replaced by AIFS forecasts?
This gives a nice three-part result:
- Whether flood-related outages are predictable at all.
- How forecast skill declines from day 1 to day 5.
- Whether skill differs among urban, peri-urban and rural locations.

We want to assess AIFS skill in predicting these floods at the locations for which observations over India are available for the period 2014-2018. If any observations are missing during that time, then skip the event.

Feel free to save plots, create jupyter notebooks, create python scripts, and log files to save your results. Be descriptive. Show all the steps you followed, the decisions you made and why you made those decisions.

Do a combination of even-specific time series and statistical analysis and also time averaged analysis to assess AIFS prediction skill on outages during the Indian monsoon.

Caution: The Prayas and IMD data is in IST but the AIFS output is in UTC time zone. The grids are similar but not identical. So beware of that. Lastly, India can roughly be defined as latitudes 5 degree North to 40 degree North and 65 degree East to 100 degrees East.

Items below marked *(proposed)* are defaults Claude filled in from the experiment design above. Change them freely.

## Research question
How far in advance can raw AIFS precipitation forecasts (1–5 day leads) identify residential electricity-supply disruption at ESMI locations during Indian flood events (2015–2018, mainly monsoon), and how much skill is lost relative to observed (IMD) rainfall?

## Definitions
- **Flood event:** an event from the Global Flood Database (Tellman et al., 2021) that inundates land within 20 km of an ESMI location, and that falls inside that location's ESMI coverage period. This rebuilds the "15 events" of Verschuur & Balakrishnan (2024) (the authors did not share their list). Events where the affected location has missing ESMI data during the event window are skipped.
- **Outage minute:** a minute with voltage < 130 V (as in Verschuur & Balakrishnan). Exact-0 minutes are kept as a sensitivity check.
- **Outcome** *(proposed)*: binary "disruption day" = daily outage minutes above that station's 90th percentile (from all its non-event days). Secondary outcome: excess outage minutes relative to the station's same-month, same-day-of-week median.
- **Predictor:** 24 h and 48 h accumulated precipitation at the location, on the IMD day (03 UTC to 03 UTC), from AIFS at leads 1–5 days, and from IMD as the perfect-rainfall benchmark.
- **Spatial match** *(proposed)*: nearest 0.25° grid cell, plus the mean and max over a 3×3 neighbourhood (~±0.25°, ~25 km) to allow for small forecast displacement errors.
- **Time window** *(proposed)*: event days (GFD start–end) plus 3 days either side, as the event time series. Lags 0–2 days in the model.

## Method *(proposed)*
1. Event-specific time series: observed outages vs. IMD vs. AIFS rain at each lead, per event and location.
2. Logistic regression (and a mixed-effects version with a random intercept per station) of disruption day on forecast rainfall, by lead time.
3. Leave-one-flood-event-out cross-validation. Scores: Brier skill score, ROC-AUC, reliability.
4. Baselines: climatology (station/month base rate), outage persistence (yesterday's outage), IMD perfect rainfall. IFS forecasts are not available for 2014–2018 in `forecasts/aifs/ifs/`, so they are left out unless another source turns up.
5. Time-averaged skill over the whole monsoon (JJAS, all station-days), in addition to the event-only analysis.
6. Split skill by ESMI category: urban (State Capital, District HQ), peri-urban (Other Municipal Area), rural (Gram Panchayat).
- Controls: station, month/season and day of week (through the baseline or fixed effects).

## Deliverables
- [x] Cleaned daily outage panel (`data/esmi_daily.csv.gz`), hourly summary (`data/esmi_hourly.csv.gz`)
- [x] Location → coordinates → grid-cell lookup (`data/locations.csv`); 40 kept flood stations still at city centroid
- [x] Rebuilt flood-event list with affected stations (`data/flood_events.csv`, `data/flood_event_stations.csv`): 11 events / 9 episodes, 124 station-events
- [x] India subsets of AIFS precipitation (`data/aifs_india/`)
- [x] Daily location-level panel with IMD + AIFS rain (by lead) + outage metrics (`data/panel_daily.parquet`)
- [x] Figures (`outputs/figures/`), scripts (`scripts/`), Slurm logs (`logs/`)
- [x] Analysis notebook (`notebooks/01_aifs_outage_skill.ipynb`) and written summary (`outputs/SUMMARY.md`), first pass 2026-09-23

## Tooling preferences
- Python with xarray, pandas, pyarrow, rasterio/geopandas, statsmodels/scikit-learn.
- Environment: the owner's `jupyter_notebook` conda env (`/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook`). This is the owner's choice, even though the cluster policy discourages Conda.
  Added 2026-09-23 via pip with all existing packages pinned (backups in `env_backup/`): rasterio, geopandas, pyogrio, statsmodels, pyarrow.
- All heavy work runs in Slurm jobs (`scripts/*.sbatch`, logs in `logs/`).
- Output location: `data/` (derived data), `outputs/` (tables, figures).
