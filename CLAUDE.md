# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

This directory holds **raw data only**: no code, build system, tests, or git repo yet. The goal is to study how floods and heavy rainfall affect India's electricity supply quality by matching gridded daily rainfall (IMD, NetCDF) against minute-level voltage readings (Prayas ESMI, CSV) at each location.

- Data fields, quirks, and open questions: @docs/DATA.md
- Research question, definitions, and deliverables: @docs/TASK.md

**Five voltage CSVs are truncated** (details in DATA.md). Don't read gaps late in those periods as real outages.

`/scratch/users/ag4680/forecasts/aifs` is attached as an extra working directory, but `.claude/settings.json` denies Edit/Write there. Treat it as read-only reference.

## Environment (Sherlock HPC)

- Run no Python or heavy processing on the login node. Use `sh_dev` / `salloc`, or submit with `sbatch` (set `-p`, `--time`, `--mem`, `--cpus-per-task`).
- The shell profile auto-loads modules (python/3.12.1, cdo/2.1.1, nco/4.8.0, ncview/2.1.7, netcdf). Every Bash call prints a wall of Lmod dependency warnings plus a `conda-libmamba-solver ... libarchive.so.19` error. These are noise; ignore them unless a tool actually fails.
- `ncdump -h`, `cdo`, and `nco` are available for inspecting and manipulating the NetCDF files.
