"""Build notebooks/01_aifs_outage_skill.ipynb: a walk-through of the analysis that reads the saved
outputs (no heavy computation). Executed by scripts/09_make_notebook.sbatch with nbconvert."""
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# AIFS rain forecasts and electricity disruption during Indian floods\n"
       "Walk-through of the pipeline (`scripts/01`–`08`). This notebook only reads saved outputs; "
       "all heavy steps ran as Slurm jobs (logs in `logs/`). The written summary is `outputs/SUMMARY.md`."),
    code("from pathlib import Path\nimport pandas as pd\nfrom IPython.display import Image, display, Markdown\n"
         "ROOT = Path('..').resolve()\npd.set_option('display.width', 160, 'display.max_columns', 30)"),
    md("## 1. Data checks\n**AIFS units and timing** (`scripts/05_check_aifs_units.py`): IMD mm / raw AIFS ≈ 896 "
       "⇒ AIFS precipitation is metres per 6 h step; `leadtime` = 6…120 h from 00 UTC."),
    code("print((ROOT/'logs/aifs_units_check.log').read_text()[-1500:])"),
    md("## 2. Station coordinates"),
    code("loc = pd.read_csv(ROOT/'data/locations.csv')\nprint(loc.precision.value_counts())\n"
         "display(Image(str(ROOT/'outputs/figures/02_locations_map.png'), width=600))"),
    md("## 3. Flood events (GFD) matched to stations\nRiver-channel pixels (flooded in ≥ 3 of 26 events) are "
       "masked; a station is affected if ≥ 1 km² of flooding lies within 20 km, the whole event window "
       "(start − 3 d to end + 3 d) is inside its coverage, and every day is observed."),
    code("ev = pd.read_csv(ROOT/'data/flood_events.csv')\ndisplay(ev[ev.used])\n"
         "display(Image(str(ROOT/'outputs/figures/04_flood_events_map.png'), width=650))"),
    md("## 4. Daily panel"),
    code("print((ROOT/'outputs/06_panel_summary.txt').read_text())"),
    code("display(Image(str(ROOT/'outputs/figures/08_rain_vs_imd.png'), width=800))\n"
         "display(pd.read_csv(ROOT/'outputs/08_rain_vs_imd.csv').pivot(index='lead', columns='sp', values='r').round(3))"),
    md("## 5. Event time series\nStation-mean outage minutes (top) and rain (bottom) for each episode."),
    code("display(Image(str(ROOT/'outputs/figures/08_event_timeseries.png'), width=1000))"),
    md("## 6. Rain–outage association (in-sample)\nLogistic coefficient on log(1 + rain), climatology offset; "
       "and a random-intercept-per-station version."),
    code("display(pd.read_csv(ROOT/'outputs/07_coefficients.csv').round(4))\n"
         "display(pd.read_csv(ROOT/'outputs/07_mixed_effects.csv').round(4))"),
    md("## 7. Cross-validated skill\nLeave-one-flood-episode-out (event windows) and leave-one-year-out (JJAS)."),
    code("S = pd.read_csv(ROOT/'outputs/07_skill.csv')\n"
         "keep = ['clim','imd','imd48','pers_1','aifs_1','aifs_2','aifs_3','aifs_4','aifs_5','aifs_pers_1','aifs_pers_5']\n"
         "for smp, tr in [('event windows','event-only'), ('event days','event-only'), ('event windows','all days'), ('JJAS all','all days')]:\n"
         "    d = S[(S.spatial=='m3') & (S.area_type=='all') & (S['sample']==smp) & (S.train==tr) & S.model.isin(keep)]\n"
         "    display(Markdown(f'**{smp}**, trained on {tr}, n = {int(d.n.iloc[0]):,}'))\n"
         "    display(d.set_index('model').loc[keep, ['bss','bss_lo','bss_hi','auc','auc_lo','auc_hi']].round(3))"),
    code("display(Image(str(ROOT/'outputs/figures/08_skill_vs_lead.png'), width=900))\n"
         "display(Image(str(ROOT/'outputs/figures/08_reliability.png'), width=450))"),
    md("### Sensitivity to the spatial match (AUC, event windows, event-only training)"),
    code("d = S[(S.area_type=='all') & (S['sample']=='event windows') & (S.train=='event-only') & S.model.isin(keep)]\n"
         "display(d.pivot(index='model', columns='spatial', values='auc').loc[keep].round(3))"),
    md("## 8. Urban / peri-urban / rural"),
    code("d = S[(S.area_type!='all') & S.model.isin(['clim','imd','pers_1','aifs_1','aifs_3','aifs_5'])]\n"
         "display(d.pivot_table(index=['sample','area_type'], columns='model', values='auc').round(3))\n"
         "display(Image(str(ROOT/'outputs/figures/08_skill_by_area.png'), width=1000))"),
    md("## 9. Skill by episode"),
    code("E = pd.read_csv(ROOT/'outputs/07_skill_by_episode.csv')\n"
         "display(E[E.model.isin(['imd','pers_1','aifs_1','aifs_5'])].pivot_table(index=['episode','events','n'], columns='model', values='auc').round(3))"),
    md("## 10. Conclusions\nSee `outputs/SUMMARY.md`: rain raises disruption odds significantly, but cross-validated "
       "skill is small (AUC ≈ 0.56–0.57 on flood windows); AIFS matches IMD on event windows and loses little "
       "from day 1 to day 5; persistence wins at day 1, AIFS wins at days 2–5; area differences are within noise."),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
out = ROOT / "notebooks"; out.mkdir(exist_ok=True)
nbf.write(nb, out / "01_aifs_outage_skill.ipynb")
print("wrote", out / "01_aifs_outage_skill.ipynb")
