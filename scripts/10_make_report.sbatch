#!/bin/bash
#SBATCH -J report
#SBATCH -p normal
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Build report tables from saved outputs, then compile outputs/report/report.pdf.
ENV=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook
cd /scratch/users/ag4680/flood_analysis
$ENV/bin/python scripts/10_make_report.py || exit 1
ml system texlive/2019
cd outputs/report
for i in 1 2; do pdflatex -interaction=nonstopmode -halt-on-error report.tex > pdflatex_run$i.log || { tail -40 pdflatex_run$i.log; exit 1; }; done
grep -E 'Warning|Overfull' pdflatex_run2.log | head -30
ls -la report.pdf
