"""Generate LaTeX tables for outputs/report/report.tex from the saved analysis outputs.
Every number in the report comes from these CSVs, so re-running 04-08 and then this script
(scripts/10_make_report.sbatch) keeps the PDF in sync."""
from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "outputs/report/tables"
T.mkdir(parents=True, exist_ok=True)

LABEL = {"clim": "Climatology", "imd": "IMD, day D", "imd48": "IMD, 48 h", "imd_lag02": "IMD, lags 0--2"}
for L in range(1, 6):
    LABEL[f"pers_{L}"] = f"Persistence, lead {L}"
    LABEL[f"aifs_{L}"] = f"AIFS 24 h, lead {L}"
    LABEL[f"aifs48_{L}"] = f"AIFS 48 h, lead {L}"
    LABEL[f"aifs_pers_{L}"] = f"AIFS + persistence, lead {L}"


def tex(s):
    return re.sub(r"([&%_#$])", r"\\\1", str(s))


def write(name, body):
    (T / f"{name}.tex").write_text(body)


def fmt(x, d=3):
    return "--" if pd.isna(x) else f"{x:.{d}f}"


S = pd.read_csv(ROOT / "outputs/07_skill.csv")
S = S[S.area_type.fillna("all") == S.area_type.fillna("all")]

# ---- main skill tables with CIs ----
MODELS = ["clim", "imd", "imd48", "imd_lag02"] + [f"pers_{L}" for L in (1, 2, 3, 5)] + \
         [f"aifs_{L}" for L in range(1, 6)] + ["aifs48_2", "aifs48_5", "aifs_pers_1", "aifs_pers_3", "aifs_pers_5"]
GROUP_BREAKS = {"pers_1", "aifs_1", "aifs48_2", "aifs_pers_1"}


def skill_table(sample, train, name):
    d = S[(S.spatial == "m3") & (S.area_type == "all") & (S["sample"] == sample) & (S.train == train)]
    d = d.set_index("model")
    rows = []
    for m in MODELS:
        if m not in d.index:
            continue
        r = d.loc[m]
        if m in GROUP_BREAKS:
            rows.append(r"\midrule")
        rows.append(f"{LABEL[m]} & {fmt(r.brier, 4)} & {fmt(r.bss)} & [{fmt(r.bss_lo)}, {fmt(r.bss_hi)}] & "
                    f"{fmt(r.auc)} & [{fmt(r.auc_lo)}, {fmt(r.auc_hi)}] \\\\")
    n, br = int(d.n.iloc[0]), d.base_rate.iloc[0]
    body = (r"\begin{tabular}{lrrcrc}\toprule" "\n"
            r"Model & Brier & BSS & 95\% CI & AUC & 95\% CI \\ \midrule" "\n" + "\n".join(rows[1:] if rows[0] == r"\midrule" else rows) +
            "\n" r"\bottomrule\end{tabular}")
    write(name, body)
    return n, br


meta = {}
for smp, tr, name in [("event windows", "event-only", "skill_event_windows"),
                      ("event days", "event-only", "skill_event_days"),
                      ("event windows", "all days", "skill_event_windows_alltrain"),
                      ("JJAS all", "all days", "skill_jjas"),
                      ("JJAS event windows", "all days", "skill_jjas_eventwin")]:
    meta[name] = skill_table(smp, tr, name)
write("skill_meta", "\n".join(
    f"\\newcommand{{\\n{k.replace('_', '')}}}{{{n:,}}}\\newcommand{{\\br{k.replace('_', '')}}}{{{br * 100:.1f}\\%}}"
    for k, (n, br) in meta.items()))

# ---- spatial sensitivity ----
sp_models = ["clim", "imd", "pers_1", "aifs_1", "aifs_3", "aifs_5", "aifs_pers_1"]
rows = []
for smp, tr, lab in [("event windows", "event-only", "Event windows"), ("JJAS all", "all days", "JJAS all days")]:
    d = S[(S.area_type == "all") & (S["sample"] == smp) & (S.train == tr) & S.model.isin(sp_models)]
    pv = d.pivot(index="model", columns="spatial", values="auc").loc[sp_models]
    for m in sp_models:
        rows.append(f"{lab} & {LABEL[m]} & {fmt(pv.loc[m, 'c'])} & {fmt(pv.loc[m, 'm3'])} & {fmt(pv.loc[m, 'x3'])} \\\\")
    rows.append(r"\midrule")
write("spatial_sensitivity", r"\begin{tabular}{llrrr}\toprule Sample & Model & Centre cell & 3$\times$3 mean & 3$\times$3 max \\ \midrule"
      "\n" + "\n".join(rows[:-1]) + "\n" r"\bottomrule\end{tabular}")

# ---- area type ----
ar_models = ["clim", "imd", "pers_1", "aifs_1", "aifs_3", "aifs_5"]
rows = []
for smp, lab in [("event windows", "Event windows"), ("JJAS all", "JJAS all days")]:
    for at in ["urban", "peri-urban", "rural"]:
        d = S[(S.spatial == "m3") & (S.area_type == at) & (S["sample"] == smp) & S.model.isin(ar_models)].set_index("model")
        if d.empty:
            continue
        cells = " & ".join(f"{fmt(d.loc[m, 'auc'])}" for m in ar_models)
        rows.append(f"{lab} & {at} & {int(d.n.iloc[0]):,} & {cells} \\\\")
    rows.append(r"\midrule")
hdr = " & ".join(["Clim.", "IMD", "Pers. L1", "AIFS L1", "AIFS L3", "AIFS L5"])
write("area_type", r"\begin{tabular}{llr" + "r" * len(ar_models) + r"}\toprule Sample & Area & $n$ & " + hdr +
      r" \\ \midrule" "\n" + "\n".join(rows[:-1]) + "\n" r"\bottomrule\end{tabular}")

# ---- coefficients ----
C = pd.read_csv(ROOT / "outputs/07_coefficients.csv").set_index("model")
M = pd.read_csv(ROOT / "outputs/07_mixed_effects.csv").set_index("model")
rows = []
for m in ["imd"] + [f"aifs_{L}" for L in range(1, 6)]:
    c, mm = C.loc[m], M.loc[m]
    p = "$<$0.001" if c.p < 0.001 else f"{c.p:.3f}"
    rows.append(f"{LABEL[m]} & {c.coef_log1p_rain:.3f} & {c.se:.3f} & {p} & {c.odds_ratio_per_e_fold:.2f} & "
                f"{mm.coef_log1p_rain:.3f} & {mm.sd:.3f} & {mm.station_sd:.2f} \\\\")
write("coefficients", r"\begin{tabular}{lrrrrrrr}\toprule & \multicolumn{4}{c}{GLM, climatology offset} & "
      r"\multicolumn{3}{c}{Random intercept per station} \\ \cmidrule(lr){2-5}\cmidrule(lr){6-8}"
      r"Predictor & $\beta$ & SE & $p$ & OR & $\beta$ & SD & station SD \\ \midrule" "\n" + "\n".join(rows) +
      "\n" r"\bottomrule\end{tabular}")

# ---- episodes ----
E = pd.read_csv(ROOT / "outputs/07_skill_by_episode.csv")
ev = pd.read_csv(ROOT / "data/flood_events.csv", parse_dates=["began", "ended"])
pv = (E.groupby("episode")[["events", "n", "base_rate"]].first()
      .join(E[E.model.isin(["clim", "imd", "pers_1", "aifs_1", "aifs_5"])]
            .pivot(index="episode", columns="model", values="auc"))
      .reset_index())
rows = []
for _, r in pv.iterrows():
    ids = [int(x) for x in str(r.events).split("+")]
    e = ev[ev.event_id.isin(ids)]
    dates = f"{e.began.min():%d %b %Y} -- {e.ended.max():%d %b %Y}"
    ctry = "/".join(sorted(set(e.country)))
    nst = int(e.n_keep_strict.sum())
    rows.append(f"{int(r.episode)} & {r.events} & {tex(ctry)} & {dates} & {nst} & {int(r.n)} & {r.base_rate * 100:.1f} & "
                + " & ".join(fmt(r.get(m)) for m in ["clim", "imd", "pers_1", "aifs_1", "aifs_5"]) + r" \\")
write("episodes", r"\begin{tabular}{rllllrrrrrrrr}\toprule Ep. & GFD IDs & Country & Dates & Stn-events & $n$ & Base \% & "
      r"Clim. & IMD & Pers. L1 & AIFS L1 & AIFS L5 \\ \midrule" "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}")

# ---- flood events table (all 26) ----
rows = []
for _, r in ev.sort_values("began").iterrows():
    rows.append(f"{r.event_id} & {tex(r.country)} & {r.began:%Y-%m-%d} & {r.ended:%Y-%m-%d} & {tex(r.main_cause)[:34]} & "
                f"{r.n_affected} & {r.n_affected_in_coverage} & {r.n_keep_strict} & {r.n_keep_raw_rule} & "
                f"{'yes' if r.used else ''} \\\\")
write("flood_events", r"\begin{tabular}{rllllrrrrl}\toprule ID & Country & Began & Ended & Cause & Affected & In cov. & Kept & Kept (raw) & Used \\ \midrule"
      "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}")

# ---- rain vs IMD ----
R = pd.read_csv(ROOT / "outputs/08_rain_vs_imd.csv")
rows = []
for L in range(1, 6):
    d = R[R.lead == L].set_index("sp")
    rows.append(f"{L} & " + " & ".join(f"{d.loc[s, 'r']:.3f}" for s in ["c", "m3", "x3"]) + " & " +
                " & ".join(f"{d.loc[s, 'bias']:+.2f}" for s in ["c", "m3", "x3"]) + r" \\")
write("rain_vs_imd", r"\begin{tabular}{rrrrrrr}\toprule & \multicolumn{3}{c}{Pearson $r$ with IMD} & \multicolumn{3}{c}{Bias AIFS$-$IMD (mm/day)} \\"
      r"\cmidrule(lr){2-4}\cmidrule(lr){5-7} Lead (d) & centre & 3$\times$3 mean & 3$\times$3 max & centre & 3$\times$3 mean & 3$\times$3 max \\ \midrule"
      "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}")

# ---- units check excerpt ----
u = (ROOT / "logs/aifs_units_check.log").read_text()
rat = [float(m.group(1)) for m in re.finditer(r"^\s*\d{4}-\d{2}-\d{2}\s+[\d.]+\s+[\d.]+\s+([\d.]+)", u, re.M)]
med = f"{pd.Series(rat).median():.0f}"
cor = re.search(r"mean spatial correlation, lead-1 day: ([\d.]+)", u).group(1)
write("units_meta", f"\\newcommand{{\\unitsratio}}{{{med}}}\\newcommand{{\\unitscorr}}{{{cor}}}")
print("tables written to", T)
