#!/bin/bash
#SBATCH -J figures
#SBATCH -p normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=16GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Figures from scripts/06 and 07 outputs (scripts/08_figures.py).
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
cd /scratch/users/ag4680/flood_analysis
$PY scripts/08_figures.py
