"""Figures for the AIFS outage-skill analysis (reads outputs of scripts/06 and 07).

  08_skill_vs_lead.png        BSS and ROC-AUC vs lead: event windows (LOEO-CV) and JJAS (LOYO-CV)
  08_skill_by_area.png        same, split urban / peri-urban / rural
  08_event_timeseries.png     per episode: outage minutes, IMD rain and AIFS rain at leads 1-5
  08_reliability.png          reliability of event-window CV predictions
  08_rain_vs_imd.png          AIFS vs IMD station rain: correlation and mean by lead (JJAS)
Palette: reference categorical slots (blue = AIFS, orange = IMD, aqua = persistence), gray =
climatology; AIFS leads in the time series use the blue sequential ramp (light = long lead).
"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs/figures"
LEADS = [1, 2, 3, 4, 5]
AIFS, IMD, PERS = "#2a78d6", "#eb6834", "#1baf7a"
MUTED, INK2, GRID, SURF = "#898781", "#52514e", "#e6e5e1", "#fcfcfb"
RAMP = ["#0d366b", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef"]   # lead 1 (dark) -> 5 (light)

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "lines.linewidth": 2, "legend.frameon": False})


def lead_panel(ax, d, metric, title, ylab, ref0):
    a = d[d.model.isin([f"aifs_{L}" for L in LEADS])].copy()
    a["lead"] = a.model.str[-1].astype(int)
    a = a.sort_values("lead")
    pr = d[d.model.isin([f"pers_{L}" for L in LEADS])].copy()
    pr["lead"] = pr.model.str[-1].astype(int)
    pr = pr.sort_values("lead")
    lo, hi = f"{metric}_lo", f"{metric}_hi"
    if a[lo].notna().any():
        ax.fill_between(a.lead.values, a[lo].values, a[hi].values, color=AIFS, alpha=0.15, lw=0)
    ax.plot(a.lead.values, a[metric].values, "-o", color=AIFS, ms=6, label="AIFS rain")
    ax.plot(pr.lead.values, pr[metric].values, "-s", color=PERS, ms=6, label="Persistence (outage on day D−lead)")
    imd = d[d.model == "imd"]
    if len(imd):
        v = imd[metric].iloc[0]
        ax.axhline(v, color=IMD, lw=2, ls="--", label="IMD observed rain (perfect)")
        ax.annotate("IMD", (5.08, v), color=INK2, va="center", fontsize=9, annotation_clip=False)
    ax.axhline(ref0, color=MUTED, lw=1.2, ls=":", label="Climatology")
    ax.annotate("AIFS", (5.08, a[metric].iloc[-1]), color=INK2, va="center", fontsize=9, annotation_clip=False)
    ax.annotate("Persist.", (5.08, pr[metric].iloc[-1]), color=INK2, va="center", fontsize=9, annotation_clip=False)
    ax.set_xticks(LEADS); ax.set_xlabel("Lead time (days)"); ax.set_ylabel(ylab); ax.set_title(title, loc="left")


def fig_skill(S):
    s = S[(S.spatial == "m3") & (S.area_type == "all")]
    panels = [("event windows", "event-only", "Flood-event windows (leave-one-episode-out)"),
              ("JJAS all", "all days", "All monsoon days, JJAS (leave-one-year-out)")]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5), constrained_layout=True)
    for j, (smp, tr, ttl) in enumerate(panels):
        d = s[(s["sample"] == smp) & (s.train == tr)]
        n, br = int(d.n.iloc[0]), d.base_rate.iloc[0]
        lead_panel(axes[0, j], d, "bss", f"{ttl}\nn = {n:,} station-days, base rate {br:.1%}",
                   "Brier skill score vs climatology", 0.0)
        lead_panel(axes[1, j], d, "auc", "", "ROC-AUC", float(d[d.model == "clim"].auc.iloc[0]))
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.05))
    fig.savefig(FIG / "08_skill_vs_lead.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def fig_area(S):
    s = S[(S.spatial == "m3") & (S.area_type != "all")]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), sharey="row", constrained_layout=True)
    for j, at in enumerate(["urban", "peri-urban", "rural"]):
        for i, (smp, tr, ttl) in enumerate([("event windows", "event-only", "Event windows"),
                                            ("JJAS all", "all days", "JJAS all days")]):
            d = s[(s.area_type == at) & (s["sample"] == smp) & (s.train == tr)]
            ax = axes[i, j]
            if d.empty:
                ax.set_visible(False); continue
            lead_panel(ax, d, "auc", f"{at.capitalize()} · {ttl}\nn = {int(d.n.iloc[0]):,}",
                       "ROC-AUC" if j == 0 else "", float(d[d.model == "clim"].auc.iloc[0]))
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.05))
    fig.savefig(FIG / "08_skill_by_area.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def fig_timeseries(P, eps):
    P = P[P.episode.notna()]
    n = len(eps)
    ncol = 3
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow * 2, ncol, figsize=(14, 3.3 * nrow * 2 / 1.25),
                             gridspec_kw={"height_ratios": [1, 1.2] * nrow}, constrained_layout=True)
    for k, (e, r) in enumerate(eps.iterrows()):
        row, col = 2 * (k // ncol), k % ncol
        d = P[P.episode == e]
        g = d.groupby("date")
        t = g.size().index
        axo, axr = axes[row, col], axes[row + 1, col]
        axo.plot(t.values, g.out_min.mean().values, color=INK2, lw=2)
        axo.fill_between(t.values, g.out_min.quantile(0.25).values, g.out_min.quantile(0.75).values, color=MUTED, alpha=0.25, lw=0)
        axo.set_title(f"Episode {int(e)} · GFD {r.events} · {d.location.nunique()} stations", loc="left", fontsize=10)
        axo.set_ylabel("Outage min/day")
        for L in LEADS[::-1]:
            axr.plot(t.values, g[f"aifs_l{L}_m3"].mean().values, color=RAMP[L - 1], lw=1.6, label=f"AIFS lead {L} d")
        axr.plot(t.values, g["imd_m3"].mean().values, color=IMD, lw=2.4, label="IMD observed")
        axr.set_ylabel("Rain mm/day")
        for ax in (axo, axr):
            ev = d[d.in_event]
            if len(ev):
                ax.axvspan(ev.date.min(), ev.date.max(), color="#cde2fb", alpha=0.35, lw=0)
            ax.tick_params(axis="x", labelsize=8, rotation=30)
    for k in range(n, nrow * ncol):
        axes[2 * (k // ncol), k % ncol].set_visible(False)
        axes[2 * (k // ncol) + 1, k % ncol].set_visible(False)
    h, l = axes[1, 0].get_legend_handles_labels()
    fig.legend(h[::-1], l[::-1], loc="lower center", ncol=6, bbox_to_anchor=(0.5, -0.03))
    fig.suptitle("Flood episodes: station-mean outage minutes (line, IQR shaded) and rain; "
                 "light-blue band = GFD flood dates", x=0.01, ha="left", fontweight="bold")
    fig.savefig(FIG / "08_event_timeseries.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_reliability(pe):
    fig, ax = plt.subplots(figsize=(5.5, 5.2), constrained_layout=True)
    ax.plot([0, 0.5], [0, 0.5], color=MUTED, lw=1, ls=":")
    for m, c, lab in [("clim", MUTED, "Climatology"), ("imd", IMD, "IMD observed rain"),
                      ("aifs_1", AIFS, "AIFS lead 1 d"), ("aifs_5", "#86b6ef", "AIFS lead 5 d")]:
        q = pd.qcut(pe[f"p_{m}"], 8, duplicates="drop")
        g = pe.groupby(q, observed=True).agg(p=(f"p_{m}", "mean"), y=("y", "mean"), n=("y", "size"))
        ax.plot(g.p.values, g.y.values, "-o", color=c, ms=6, label=lab)
    ax.set_xlabel("Forecast probability of disruption day")
    ax.set_ylabel("Observed frequency")
    ax.set_title("Reliability, flood-event windows (CV)", loc="left")
    ax.legend(loc="upper left")
    fig.savefig(FIG / "08_reliability.png", dpi=160)
    plt.close(fig)


def fig_rain(P):
    j = P[P.date.dt.month.between(6, 9)]
    rows = []
    for L in LEADS:
        for sp in ["c", "m3", "x3"]:
            d = j[[f"aifs_l{L}_{sp}", f"imd_{sp}"]].dropna()
            rows.append(dict(lead=L, sp=sp, r=np.corrcoef(d.iloc[:, 0], d.iloc[:, 1])[0, 1],
                             bias=d.iloc[:, 0].mean() - d.iloc[:, 1].mean()))
    R = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), constrained_layout=True)
    names = {"c": "centre cell", "m3": "3×3 mean", "x3": "3×3 max"}
    cols = {"c": "#86b6ef", "m3": AIFS, "x3": "#0d366b"}
    for sp in ["c", "m3", "x3"]:
        d = R[R.sp == sp]
        axes[0].plot(d.lead.values, d.r.values, "-o", color=cols[sp], ms=6, label=names[sp])
        axes[1].plot(d.lead.values, d.bias.values, "-o", color=cols[sp], ms=6, label=names[sp])
        axes[0].annotate(names[sp], (5.1, d.r.iloc[-1]), color=INK2, fontsize=9, va="center", annotation_clip=False)
    axes[0].set_title("Correlation of AIFS with IMD daily rain (JJAS, station days)", loc="left")
    axes[0].set_ylabel("Pearson r"); axes[1].set_ylabel("AIFS − IMD (mm/day)")
    axes[1].axhline(0, color=MUTED, lw=1)
    axes[1].set_title("Mean bias", loc="left")
    for ax in axes:
        ax.set_xticks(LEADS); ax.set_xlabel("Lead time (days)")
    axes[1].legend()
    fig.savefig(FIG / "08_rain_vs_imd.png", dpi=160)
    plt.close(fig)
    R.to_csv(ROOT / "outputs/08_rain_vs_imd.csv", index=False, float_format="%.4f")


def main():
    S = pd.read_csv(ROOT / "outputs/07_skill.csv")
    fig_skill(S); fig_area(S)
    pe = pd.read_parquet(ROOT / "data/cv_pred_event.parquet")
    fig_reliability(pe)
    P = pd.read_parquet(ROOT / "data/panel_daily.parquet")
    import importlib.util
    spec = importlib.util.spec_from_file_location("m", ROOT / "scripts/07_model_skill.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    Pp, eps = m.prepare()
    P = P.merge(Pp[["location", "date", "episode"]], on=["location", "date"], how="left")
    fig_timeseries(P[P.in_window], eps)
    fig_rain(P)


if __name__ == "__main__":
    main()
