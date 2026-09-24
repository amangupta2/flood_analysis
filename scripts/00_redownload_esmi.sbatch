#!/bin/bash
#SBATCH -J esmi_redownload
#SBATCH -p normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=2GB
#SBATCH -o /scratch/users/ag4680/flood_analysis/logs/%x_%j.log
# Re-download the 5 truncated ESMI CSVs (original CSV format) from Harvard Dataverse doi:10.7910/DVN/CLLZZM.
# The dataset has a required guestbook: POST the response (redownload/guestbook.json, approved by the
# project owner) to get a short-lived signed URL, then download. Each file is verified against the
# originalFileSize reported by the Dataverse API. Files land in redownload/; originals are untouched.
cd /scratch/users/ag4680/flood_analysis/redownload
while read id size name; do
  f="ESMI minute-wise voltage data ${name}.csv"
  url=$(curl -s -X POST -H "Content-Type: application/json" -d @guestbook.json \
        "https://dataverse.harvard.edu/api/access/datafile/${id}?format=original" | grep -oP '"signedUrl":"\K[^"]+')
  [ -z "$url" ] && { echo "FAIL $f: no signed URL"; continue; }
  curl -sSL --retry 5 -o "$f" "$url"
  act=$(stat -c %s "$f")
  if [ "$act" = "$size" ]; then echo "OK   $f ($act bytes)"; else echo "FAIL $f expected $size got $act"; fi
done <<'LIST'
3360857 206629089 2016 Jan-June
3360856 233023214 2016 July-Dec
3362275 179365840 2017 May-Aug
3362278 166259841 2017 Sept-Dec
3362279 140188421 2018 June-Aug
LIST
