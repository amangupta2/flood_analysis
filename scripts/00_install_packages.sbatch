#!/bin/bash
#SBATCH -J env_install
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Add rasterio, geopandas, statsmodels, pyarrow to the jupyter_notebook env WITHOUT changing any
# existing package: every currently installed package is pinned via a pip constraints file, so pip
# can only add new packages (resolution fails rather than upgrading/downgrading anything).
set -u
E=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook
PY=$E/bin/python
B=/scratch/users/ag4680/flood_analysis/env_backup
export PIP_CACHE_DIR=$SCRATCH/.cache/pip PYTHONNOUSERSITE=1
TS=$(date +%Y%m%d_%H%M%S)
NEW="rasterio geopandas statsmodels pyarrow"

echo "== 1. backups ($TS)"
/home/groups/aditis2/ag4680/miniconda3/bin/conda list -p $E --explicit > $B/conda_explicit_$TS.txt 2>/dev/null
/home/groups/aditis2/ag4680/miniconda3/bin/conda list -p $E > $B/conda_list_$TS.txt 2>/dev/null
$PY -m pip list --format=freeze > $B/pip_before_$TS.txt
wc -l $B/*_$TS.txt

echo "== 2. constraints: pin every installed package"
grep -v -e '^-e' -e ' @ ' $B/pip_before_$TS.txt > $B/constraints_$TS.txt
wc -l $B/constraints_$TS.txt

echo "== 3. dry run"
$PY -m pip install --dry-run --only-binary=:all: -c $B/constraints_$TS.txt $NEW 2>&1 | tail -15
[ ${PIPESTATUS[0]} -eq 0 ] || { echo "DRY RUN FAILED - nothing installed"; exit 1; }

echo "== 4. install"
$PY -m pip install --only-binary=:all: -c $B/constraints_$TS.txt $NEW 2>&1 | tail -5 || exit 1

echo "== 5. diff before/after (expect only '+' lines)"
$PY -m pip list --format=freeze > $B/pip_after_$TS.txt
diff $B/pip_before_$TS.txt $B/pip_after_$TS.txt | grep '^[<>]' | sed 's/^</- REMOVED\/CHANGED/; s/^>/+/'
$PY -m pip check 2>&1 | tail -5

echo "== 6. import tests"
$PY - <<'PY'
import importlib
for m in ["numpy","pandas","xarray","netCDF4","scipy","sklearn","matplotlib","cartopy","shapely","pyproj",
          "dask","esmpy","eccodes","torch","rasterio","geopandas","statsmodels","pyarrow","pyogrio"]:
    try:
        mod = importlib.import_module(m); print(f"OK   {m:12s} {getattr(mod,'__version__','')}")
    except Exception as e:
        print(f"FAIL {m:12s} {type(e).__name__}: {e}")
import geopandas, rasterio, pyproj
print("pyproj PROJ", pyproj.proj_version_str, "| rasterio GDAL", rasterio.__gdal_version__)
print(geopandas.GeoSeries.from_xy([77.2],[28.6], crs=4326).to_crs(32643).iloc[0])
PY
