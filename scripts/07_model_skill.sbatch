#!/bin/bash
#SBATCH -J skill
#SBATCH -p normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Logistic skill models, leave-one-episode-out and leave-one-year-out CV (scripts/07_model_skill.py).
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
cd /scratch/users/ag4680/flood_analysis
$PY scripts/07_model_skill.py
