#!/bin/bash
#SBATCH -J esmi_profile
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=32GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
cd /scratch/users/ag4680/flood_analysis
$PY -c "import pandas, numpy; print("pandas", pandas.__version__, "numpy", numpy.__version__)"
$PY scripts/01_esmi_profile_daily.py
