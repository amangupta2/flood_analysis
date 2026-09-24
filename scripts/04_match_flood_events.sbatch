#!/bin/bash
#SBATCH -J flood_match
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=32GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Match GFD flood footprints to ESMI stations (20 km rule + ESMI coverage/completeness).
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
cd /scratch/users/ag4680/flood_analysis
$PY scripts/04_match_flood_events.py
