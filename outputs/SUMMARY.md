# Can raw AIFS rain forecasts anticipate electricity disruption during Indian floods?

First complete pass, 2026-09-23. Scripts `scripts/01`–`08`, Slurm logs in `logs/`, numbers in `outputs/07_*.csv`.

## Short answer

1. **Flood-related outages are only weakly predictable from rainfall, whether the rain is forecast or observed.** Heavier rain does raise the odds of a disruption day. Each e-fold of (rain + 1) raises the odds about 1.3×, p < 10⁻⁴, and a random-intercept model per station gives the same result. But the cross-validated skill is small: Brier skill score (BSS) is about 0.005–0.01 and ROC-AUC about 0.56–0.57 on flood-event windows, against 0.54 for climatology.
2. **Skill barely declines from day 1 to day 5.** On event windows the AIFS skill is flat with lead: AUC 0.573 at day 1 and 0.572 at day 5. AIFS rain itself degrades with lead (JJAS correlation with IMD falls from 0.64 to 0.57 at the centre cell, and from 0.73 to 0.66 for the 3×3 mean). The outage signal is weak enough that this loss hardly matters.
3. **Replacing observed rain with AIFS rain costs little.** On event windows AIFS at leads 1–5 scores the same as IMD "perfect" rainfall, within noise (AUC 0.562 for IMD). Over all monsoon days (JJAS), IMD is modestly better: AUC 0.529 for IMD against 0.514 → 0.511 for AIFS from day 1 to day 5.
4. **Outage persistence is the strongest single predictor at 1 day, and AIFS rain adds to it.** Yesterday's outage gives event-window AUC 0.591; adding AIFS day-1 rain raises it to 0.615. From lead 2 onward persistence is no better than climatology (AUC 0.53–0.55), while AIFS keeps its small skill, so **AIFS beats persistence at leads 2–5**.
5. **Differences between urban, peri-urban and rural stations are within noise.** On flood-event windows, rural stations show the largest rain skill (BSS ≈ 0.02, AUC ≈ 0.59 for both IMD and AIFS), and urban the smallest. But the rural and peri-urban event samples are small (571 and 104 station-days), and the bootstrap intervals overlap.

All confidence intervals are wide: 9 flood episodes, block bootstrap over episodes. Many rain-model CIs for BSS include 0, so treat these as **weak, marginally significant signals**, not operational skill.

## What was done, and why

### Data preparation
| Step | Script | Decision | Why |
|---|---|---|---|
| ESMI daily panel | `01_esmi_profile_daily.py` | Outage minute = V < 130 V (0 V counted as outage); a day is *observed* if ≥ 90 % of its minutes are recorded | Follows Verschuur & Balakrishnan; missing rows = monitor downtime, not outages |
| Stations | `02_geocode_locations.py` | 529 stations geocoded (300 locality, 212 city centroid, 17 district); Agriculture feeders dropped | Owner decision; farm feeders are rostered |
| AIFS subset | `03_subset_aifs_india.sbatch` | Precipitation only, 5–40°N, 65–100°E, 1,818 init dates (8 missing) | Originals are read-only and 8.5 TB |
| AIFS units | `05_check_aifs_units.py` | total_precipitation is **metres per 6 h step**; init 00 UTC | IMD/AIFS ratio ≈ 896 in July 2016 (AIFS ~12 % wetter); values don't grow with lead |
| Time alignment | `06_build_panel.py` | IMD day D = 03 UTC D−1 → 03 UTC D. AIFS lead L = init 00 UTC on D−L, hours 24(L−1)+3 → 24L+3; straddling 6 h steps split in half. Lead 5 ends at 120 h, so 21 h scaled to 24 h | IST/UTC mismatch; the forecast only runs to 120 h |
| Grid | `06_build_panel.py` | IMD points coincide with AIFS points; nearest valid IMD cell, plus 3×3 mean (headline) and 3×3 max | Allows ~25 km of forecast displacement. The 3×3 mean was chosen before seeing results |

### Flood events (`04_match_flood_events.py`)
- **Source:** 26 Global Flood Database footprints (15 India-primary events in 2015–2018, plus 11 in neighbouring countries). Verschuur did not share their list, so this is our own reconstruction.
- **River-channel problem:** GFD's `flooded` band includes seasonally wet river channels. The 11 Guwahati stations "matched" 6 unrelated events, one of them in March.
  - Fix (owner-approved): ignore pixels flooded in 3 or more events, and require at least 1 km² of remaining flooding within 20 km.
  - The plain 20 km rule is kept as a sensitivity column.
- **Coverage rule:** keep a station only if the whole window (GFD start − 3 d to end + 3 d) is inside its ESMI coverage and every day is observed. This implements "skip the event if observations are missing".
- **Result:** 11 events, 124 station-events, 84 stations (plain rule: 12 events, 226 station-events).
  - Events that overlap in time (4378+4382, 4507+4508) are the same rain on the same station-days, so they are merged into **9 episodes** for cross-validation.
  - 40 of the kept stations are placed at a city centroid, not the locality itself. That is fine for 20 km buffers, but hand-fixing them (`data/locations_manual.csv`) would sharpen the flood match.

### Outcome and models (`07_model_skill.py`)
- **Disruption day:** outage minutes above the station's 90th percentile, computed over observed days with no flooding nearby. The base rate is 9.8 % over all station-days and 12.3 % in both the event windows and JJAS (rain season and flood days have more outages). It isn't exactly 10 % because the threshold comes from non-flood days only, and ties at 0 minutes mean stations whose 90th percentile is 0 count any outage.
- **Logistic models:** every model uses climatology as an offset (station × month rate, shrunk to the station rate). Predictors:
  - AIFS rain at lead L, 24 h and 48 h;
  - persistence = disruption on day D−L (what is known when a lead-L forecast is issued);
  - AIFS plus persistence;
  - IMD for the same day, 48 h, and lags 0–2.
- **Cross-validation:**
  - Leave-one-flood-episode-out: every date of the held-out episode is removed from training for all stations. Models are trained either on the other episodes' windows ("event-only", headline) or on all other days.
  - Monsoon analysis: leave-one-year-out over JJAS 2015–2018.
- **Mixed effects:** a random intercept per station (`07_mixed_effects.csv`) gives the same rain coefficients.

## Key numbers (3×3 mean, event-only training)

| | Climatology | IMD (perfect) | Persistence L1 | AIFS L1 | AIFS L3 | AIFS L5 | AIFS + pers. L1 |
|---|---|---|---|---|---|---|---|
| Event windows AUC (n = 2,508) | 0.538 | 0.562 | 0.591 | 0.573 | 0.569 | 0.572 | 0.615 |
| Event windows BSS | 0 | 0.004 | 0.014 | 0.008 | 0.007 | 0.008 | 0.020 |
| JJAS AUC (n ≈ 81,600, all-days training) | 0.499 | 0.529 | 0.563 | 0.514 | 0.513 | 0.511 | 0.571 |

Full tables, including 95 % CIs, the other spatial choices and the area split, are in `outputs/07_skill.csv`. Per-episode skill is in `outputs/07_skill_by_episode.csv`.

## Figures
- `figures/04_flood_events_map.png`: GFD footprints and matched stations
- `figures/08_event_timeseries.png`: per episode, station-mean outage minutes vs IMD and AIFS rain at leads 1–5
- `figures/08_skill_vs_lead.png`: BSS and AUC against lead, with IMD, persistence and climatology references
- `figures/08_skill_by_area.png`: urban / peri-urban / rural
- `figures/08_reliability.png`: reliability of the cross-validated probabilities
- `figures/08_rain_vs_imd.png`: AIFS vs IMD rain, correlation and bias by lead

## Caveats and open issues
- **Data quality.** Verschuur (personal communication) dropped this line of work because of ESMI data quality. The strict completeness rule protects the event sample, but monitor failures that record 0 V are counted as outages.
- **Outages are dominated by baseline supply problems.** Several episodes (e.g. 2016, 800 min/day at the start) show large outages unrelated to rain. The 90th-percentile outcome absorbs station level but not slow regime changes.
- **Flood-matching choices matter.** The masked rule removed about 45 % of the plain-rule station-events. Guwahati still matches three events on about 2 km² of residual flooding.
- **AIFS is wetter than IMD at stations during events** (see the time series). A logistic fit on log rain is insensitive to a constant bias, but not to a bias that varies between events.
- **IFS is not included** (no 2014–2018 IFS forecasts available).

## Next steps worth considering
1. Hand-fix the 40 kept city-centroid stations, then re-run `04` → `08` (a few hours of queue time).
2. Use a threshold outcome that is less sensitive to regime changes (e.g. excess minutes over a 30-day rolling median), and a count model for outage minutes.
3. Use extreme-rain indicators (e.g. the station's 95th-percentile rain) instead of log rain, since floods are about exceedance.
4. Run a sensitivity check with the plain 20 km rule, and with Domestic connections only.
