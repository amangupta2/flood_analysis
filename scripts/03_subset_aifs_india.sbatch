#!/bin/bash
#SBATCH -J aifs_subset
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4GB
#SBATCH --array=0-3
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%A_%a.log
# Cut total_precipitation over India (5-40N, 65-100E) out of every AIFS init file.
# The originals in forecasts/aifs are read-only and are never modified.
# AIFS grid: lat 90 -> -90 (descending), lon 0 -> 359.75, 0.25 deg. The IMD 0.25 deg points
# (6.5, 6.75, ... N; 66.5, 66.75, ... E) coincide with AIFS points, so no regridding is needed.
# leadtime = 6..120 h; time = 0 days since <init date> 00:00, i.e. 00 UTC initialisation.
# Each array task handles every 4th file; existing valid outputs are skipped, so re-running resumes.
set -u
SRC=/scratch/users/ag4680/forecasts/aifs
OUT=/scratch/users/ag4680/flood_analysis/data/aifs_india
mkdir -p "$OUT"
echo "ncks: $(which ncks)"

mapfile -t FILES < <(ls "$SRC"/aifs_era5_0p25_leadtime_120hrs_*.nc)
N=${#FILES[@]}
NTASK=4
done=0; skipped=0; failed=0
for ((i=SLURM_ARRAY_TASK_ID; i<N; i+=NTASK)); do
    f=${FILES[$i]}
    o="$OUT/$(basename "$f" .nc | sed 's/0p25/india_tp/').nc"
    if [[ -s "$o" ]] && ncdump -h "$o" >/dev/null 2>&1; then skipped=$((skipped+1)); continue; fi
    if ncks -O -4 -L 1 -v total_precipitation,time -d lat,5.,40. -d lon,65.,100. "$f" "$o.tmp"; then
        mv "$o.tmp" "$o"; done=$((done+1))
    else
        echo "FAILED: $f"; rm -f "$o.tmp"; failed=$((failed+1))
    fi
done
echo "task $SLURM_ARRAY_TASK_ID: $N files total, wrote $done, skipped $skipped, failed $failed"
