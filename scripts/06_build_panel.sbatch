#!/bin/bash
#SBATCH -J panel
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=48GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Daily station panel: ESMI outages + IMD + AIFS (leads 1-5) rain + flood-event flags.
# Needs data/flood_event_stations.csv (scripts/04) and data/aifs_india/ (scripts/03).
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
cd /scratch/users/ag4680/flood_analysis
$PY scripts/06_build_panel.py
