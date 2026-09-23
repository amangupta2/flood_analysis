#!/bin/bash
#SBATCH -J geocode
#SBATCH -p normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=8GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Geocode ESMI locations (Nominatim at 1 request/s + GeoNames fallback) and map them to the IMD/AIFS grids.
# Nominatim responses are cached in data/geocode_cache/, so re-runs after edits are fast.
PY=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook/bin/python
# usage: sbatch scripts/02_geocode_locations.sbatch [path/to/02_geocode_locations.py]
cd /scratch/users/ag4680/flood_analysis
$PY "${1:-scripts/02_geocode_locations.py}"
