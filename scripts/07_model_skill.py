"""Skill of IMD (perfect rainfall) and AIFS (leads 1-5) rain for predicting outage disruption days.

Outcome: disrupt = daily outage minutes above the station's 90th percentile (scripts/06).

Models (logistic GLMs; climatology enters as an offset so every model starts from it)
  clim        p = station x month disruption rate from the training fold (shrunk to the station rate)
  pers_L      offset + disrupt on day D-L (the latest outage known when a lead-L forecast is issued)
  aifs_L      offset + log1p(AIFS 24 h rain for day D at lead L)
  aifs48_L    offset + log1p(AIFS 48 h rain, days D-1..D, same init)        (L = 2..5)
  aifs_pers_L offset + log1p(AIFS rain) + disrupt(D-L)
  imd         offset + log1p(IMD rain on day D)                 perfect-rainfall benchmark
  imd48       offset + log1p(IMD 48 h rain)
  imd_lag02   offset + log1p(IMD D) + log1p(IMD D-1) + log1p(IMD D-2)

Rain = 3x3 mean around the station (headline, chosen a priori); centre cell and 3x3 max are
reported as a sensitivity check.

Cross-validation
  * Event analysis: leave-one-flood-EPISODE-out. Events whose windows overlap in time are one
    episode (4378+4382 in 2016, 4507+4508 in 2017), because they are the same rain and the same
    station-days. Held-out test rows = that episode's station-days. All dates of the held-out
    episode (all stations) are removed from training.
      E-models: trained on the other episodes' event-window days only.
      A-models: trained on every other observed station-day (all months).
  * Monsoon (JJAS) time-averaged analysis: leave-one-year-out over JJAS 2015-2018, A-models.
Scores: Brier score, Brier skill score vs climatology (BSS), ROC-AUC. 95 % CIs from a block
bootstrap (episodes for the event analysis, stations for JJAS).
All models are scored on the same rows (every predictor available).
"""
import os
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs/figures"
LEADS = [1, 2, 3, 4, 5]
K_SHRINK = 20
NBOOT = int(os.environ.get("NBOOT", 1000))          # event samples (a few thousand rows)
NBOOT_BIG = int(os.environ.get("NBOOT_BIG", 200))    # JJAS samples (~10^5 rows; AUC is the slow part)
rng = np.random.default_rng(42)
LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.append(s)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4); return np.log(p / (1 - p))


def model_specs(sp="m3"):
    specs = {"clim": [], "imd": [f"lr_imd_{sp}"], "imd48": [f"lr_imd48_{sp}"],
             "imd_lag02": [f"lr_imd_{sp}", f"lr_imd_{sp}_lag1", f"lr_imd_{sp}_lag2"]}
    for L in LEADS:
        specs[f"pers_{L}"] = [f"disrupt_lag{L}"]
        specs[f"aifs_{L}"] = [f"lr_aifs_l{L}_{sp}"]
        specs[f"aifs_pers_{L}"] = [f"lr_aifs_l{L}_{sp}", f"disrupt_lag{L}"]
        if L >= 2:
            specs[f"aifs48_{L}"] = [f"lr_aifs48_l{L}_{sp}"]
    return specs


def prepare():
    p = pd.read_parquet(ROOT / "data/panel_daily.parquet")
    p = p.sort_values(["location", "date"]).reset_index(drop=True)
    g = p.groupby("location")
    for L in LEADS:
        p[f"disrupt_lag{L}"] = g.disrupt.shift(L)
    rain = [c for c in p.columns if c.startswith(("imd_", "imd48_", "aifs_l", "aifs48_l"))]
    for c in rain:
        p[f"lr_{c}"] = np.log1p(p[c].clip(lower=0))
    for sp in ["c", "m3", "x3"]:
        for k in (1, 2):
            p[f"lr_imd_{sp}_lag{k}"] = g[f"lr_imd_{sp}"].shift(k)
    p = p[p.observed & p.disrupt.notna()].copy()

    # Episodes: merge kept events whose windows overlap in time.
    es = pd.read_csv(ROOT / "data/flood_event_stations.csv", parse_dates=["win_start", "win_end"])
    ev = (es[es.keep].groupby("event_id").agg(ws=("win_start", "min"), we=("win_end", "max"))
          .sort_values("ws"))
    epi, cur, end = {}, 0, None
    for eid, r in ev.iterrows():
        if end is None or r.ws > end:
            cur += 1; end = r.we
        else:
            end = max(end, r.we)
        epi[eid] = cur
    p["episode"] = p.event_id.map(epi)
    eps = (ev.assign(episode=ev.index.map(epi)).reset_index()
           .groupby("episode").agg(events=("event_id", lambda s: "+".join(map(str, s))),
                                    ws=("ws", "min"), we=("we", "max")))
    return p, eps


def clim_prob(train, test):
    st = train.groupby("location").disrupt.agg(["sum", "count"])
    glob = train.disrupt.mean()
    ps = (st["sum"] + K_SHRINK * glob) / (st["count"] + K_SHRINK)
    sm_ = train.groupby(["location", "month"]).disrupt.agg(["sum", "count"]).reset_index()
    sm_["ps"] = sm_.location.map(ps)
    sm_["p"] = (sm_["sum"] + K_SHRINK * sm_.ps) / (sm_["count"] + K_SHRINK)
    key = test[["location", "month"]].merge(sm_[["location", "month", "p"]], how="left",
                                            on=["location", "month"])["p"].values
    fallback = test.location.map(ps).fillna(glob).values
    return np.where(np.isnan(key), fallback, key)


def fit_predict(train, test, feats, off_tr, off_te):
    if not feats:
        return 1 / (1 + np.exp(-off_te))
    X = sm.add_constant(train[feats].values, has_constant="add")
    m = sm.GLM(train.disrupt.values, X, family=sm.families.Binomial(), offset=off_tr).fit()
    Xt = sm.add_constant(test[feats].values, has_constant="add")
    return m.predict(Xt, offset=off_te)


def scores(y, pred, pclim):
    bs, bc = np.mean((pred - y) ** 2), np.mean((pclim - y) ** 2)
    auc = roc_auc_score(y, pred) if 0 < y.sum() < len(y) else np.nan
    return bs, 1 - bs / bc, auc


def boot(df, models, block, nboot):
    """Block bootstrap of BSS and AUC; returns dict model -> (bss_lo, bss_hi, auc_lo, auc_hi)."""
    if nboot == 0:
        return {m: [np.nan] * 4 for m in models}
    groups = df[block].unique()
    idx = {g: np.where(df[block].values == g)[0] for g in groups}
    y = df.y.values
    out = {m: [] for m in models}
    for _ in range(nboot):
        take = np.concatenate([idx[g] for g in rng.choice(groups, len(groups))])
        yy, pc = y[take], df["p_clim"].values[take]
        bc = np.mean((pc - yy) ** 2)
        for m in models:
            pm = df[f"p_{m}"].values[take]
            bss = 1 - np.mean((pm - yy) ** 2) / bc
            auc = roc_auc_score(yy, pm) if 0 < yy.sum() < len(yy) else np.nan
            out[m].append((bss, auc))
    return {m: np.nanpercentile(np.array(v), [2.5, 97.5], axis=0).T.ravel() for m, v in out.items()}


def summarise(df, models, block, label, nboot=None):
    rows = []
    if nboot is None:
        nboot = NBOOT if len(df) < 20000 else NBOOT_BIG
    ci = boot(df, models, block, nboot)
    for m in models:
        bs, bss, auc = scores(df.y.values, df[f"p_{m}"].values, df.p_clim.values)
        lo_b, hi_b, lo_a, hi_a = ci[m]
        rows.append(dict(sample=label, model=m, n=len(df), base_rate=df.y.mean(), brier=bs,
                         bss=bss, bss_lo=lo_b, bss_hi=hi_b, auc=auc, auc_lo=lo_a, auc_hi=hi_a))
    return rows


def event_cv(p, eps, specs, feats_all):
    need = sorted({f for v in specs.values() for f in v})
    rows_e, rows_a = [], []
    for e, r in eps.iterrows():
        excl = (p.date >= r.ws) & (p.date <= r.we)
        test = p[(p.episode == e) & p.in_window].dropna(subset=need)
        tr_all = p[~excl].dropna(subset=need)
        tr_evt = tr_all[tr_all.in_window & tr_all.episode.notna()]
        if len(test) == 0:
            continue
        pc_te, pc_all, pc_evt = (clim_prob(tr_all, d) for d in (test, tr_all, tr_evt))
        te = test[["location", "date", "episode", "area_type", "in_event", "rel_day"]].copy()
        te["y"], te["p_clim"] = test.disrupt.values, pc_te
        ta = te.copy()
        for m, f in specs.items():
            te[f"p_{m}"] = fit_predict(tr_evt, test, f, logit(pc_evt), logit(pc_te))
            ta[f"p_{m}"] = fit_predict(tr_all, test, f, logit(pc_all), logit(pc_te))
        rows_e.append(te); rows_a.append(ta)
    return pd.concat(rows_e), pd.concat(rows_a)


def jjas_cv(p, specs):
    need = sorted({f for v in specs.values() for f in v})
    q = p[p.month.between(6, 9)].dropna(subset=need)
    q = q.assign(year=q.date.dt.year)
    out = []
    for yr in sorted(q.year.unique()):
        tr, te_ = q[q.year != yr], q[q.year == yr]
        if len(te_) == 0 or tr.disrupt.sum() == 0:
            continue
        pc_tr, pc_te = clim_prob(tr, tr), clim_prob(tr, te_)
        te = te_[["location", "date", "area_type", "in_event", "in_window", "year"]].copy()
        te["y"], te["p_clim"] = te_.disrupt.values, pc_te
        for m, f in specs.items():
            te[f"p_{m}"] = fit_predict(tr, te_, f, logit(pc_tr), logit(pc_te))
        out.append(te)
    return pd.concat(out)


def coefs(p, specs):
    """In-sample coefficients (all event-window days) for interpretation."""
    need = sorted({f for v in specs.values() for f in v})
    d = p[p.in_window & p.episode.notna()].dropna(subset=need)
    off = logit(clim_prob(p.dropna(subset=need), d))
    rows = []
    for m in ["imd"] + [f"aifs_{L}" for L in LEADS]:
        f = specs[m]
        X = sm.add_constant(d[f].values, has_constant="add")
        r = sm.GLM(d.disrupt.values, X, family=sm.families.Binomial(), offset=off).fit()
        rows.append(dict(model=m, coef_log1p_rain=r.params[1], se=r.bse[1], p=r.pvalues[1],
                         odds_ratio_per_e_fold=np.exp(r.params[1]), n=len(d)))
    return pd.DataFrame(rows)


def mixed(p, specs):
    """Random-intercept (station) logistic on event-window days, IMD and AIFS leads (in-sample)."""
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    need = sorted({f for v in specs.values() for f in v})
    d = p[p.in_window & p.episode.notna()].dropna(subset=need).copy()
    rows = []
    for m in ["imd"] + [f"aifs_{L}" for L in LEADS]:
        x = specs[m][0]
        d["x"] = d[x]
        md = BinomialBayesMixedGLM.from_formula("disrupt ~ x + C(month)", {"station": "0 + C(location)"}, d)
        r = md.fit_vb()
        i = list(md.exog_names).index("x")
        rows.append(dict(model=m, coef_log1p_rain=r.fe_mean[i], sd=r.fe_sd[i],
                         station_sd=float(np.exp(r.vcp_mean[0])), n=len(d)))
    return pd.DataFrame(rows)


def main():
    p, eps = prepare()
    log(f"rows (observed station-days with outcome): {len(p):,}")
    log("episodes:\n" + eps.to_string())
    res = []
    for sp in ["m3", "c", "x3"]:
        specs = model_specs(sp)
        models = list(specs)
        nb = None if sp == "m3" else 0          # CIs only for the headline spatial choice
        pe, pa = event_cv(p, eps, specs, None)
        res += [dict(r, spatial=sp, train="event-only") for r in summarise(pe, models, "episode", "event windows", nb)]
        res += [dict(r, spatial=sp, train="all days") for r in summarise(pa, models, "episode", "event windows", nb)]
        res += [dict(r, spatial=sp, train="event-only") for r in summarise(pe[pe.in_event], models, "episode", "event days", nb)]
        pj = jjas_cv(p, specs)
        res += [dict(r, spatial=sp, train="all days") for r in summarise(pj, models, "location", "JJAS all", nb)]
        res += [dict(r, spatial=sp, train="all days") for r in summarise(pj[pj.in_window], models, "location", "JJAS event windows", nb)]
        if sp == "m3":
            for at in ["urban", "peri-urban", "rural"]:
                res += [dict(r, spatial=sp, train="event-only", area_type=at)
                        for r in summarise(pe[pe.area_type == at], models, "episode", "event windows")]
                res += [dict(r, spatial=sp, train="all days", area_type=at)
                        for r in summarise(pj[pj.area_type == at], models, "location", "JJAS all")]
            pe.to_parquet(ROOT / "data/cv_pred_event.parquet", index=False)
            pa.to_parquet(ROOT / "data/cv_pred_event_alltrain.parquet", index=False)
            pj.to_parquet(ROOT / "data/cv_pred_jjas.parquet", index=False)
            per_ep = []
            for e, d in pe.groupby("episode"):
                for m in models:
                    bs, bss, auc = scores(d.y.values, d[f"p_{m}"].values, d.p_clim.values)
                    per_ep.append(dict(episode=e, events=eps.loc[e, "events"], model=m, n=len(d),
                                       base_rate=d.y.mean(), bss=bss, auc=auc))
            pd.DataFrame(per_ep).to_csv(ROOT / "outputs/07_skill_by_episode.csv", index=False)
            coefs(p, specs).to_csv(ROOT / "outputs/07_coefficients.csv", index=False)
            try:
                mixed(p, specs).to_csv(ROOT / "outputs/07_mixed_effects.csv", index=False)
            except Exception as ex:  # keep the main results if the VB fit fails
                log(f"mixed-effects fit failed: {ex!r}")
        log(f"done spatial={sp}")
    R = pd.DataFrame(res)
    R["area_type"] = R.get("area_type", pd.Series(index=R.index, dtype=object)).fillna("all")
    R.to_csv(ROOT / "outputs/07_skill.csv", index=False, float_format="%.4f")
    show = R[(R.spatial == "m3") & (R.area_type == "all")]
    for (s, t), d in show.groupby(["sample", "train"]):
        log(f"\n== {s} | trained on {t} | n={d.n.iloc[0]:,} base rate {d.base_rate.iloc[0]:.3f}")
        log(d[["model", "bss", "bss_lo", "bss_hi", "auc", "auc_lo", "auc_hi"]].round(3).to_string(index=False))
    (ROOT / "outputs/07_model_log.txt").write_text("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
