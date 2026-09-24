#!/bin/bash
#SBATCH -J notebook
#SBATCH -p normal
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Build and execute the walk-through notebook (reads saved outputs only).
ENV=/home/groups/aditis2/ag4680/miniconda3/envs/jupyter_notebook
cd /scratch/users/ag4680/flood_analysis
$ENV/bin/python scripts/09_make_notebook.py
export JUPYTER_RUNTIME_DIR=$SCRATCH/.jupyter_runtime/$SLURM_JOB_ID; mkdir -p $JUPYTER_RUNTIME_DIR
cd notebooks && $ENV/bin/jupyter-nbconvert --to notebook --execute --inplace --KernelManager.transport=ipc 01_aifs_outage_skill.ipynb
