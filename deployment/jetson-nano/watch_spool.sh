#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dga-edge :: spool-directory watcher
#
# Polls /var/lib/dga-edge/spool for new *.csv files, diagnoses each one, and
# writes results to /var/lib/dga-edge/out. Processed inputs move to
# /var/lib/dga-edge/done so a sample is never diagnosed twice.
#
# No inotify dependency: on JetPack 4.6.4 this must work with a bare Python 3.6
# and standard Ubuntu 18.04 packages, so a simple poll loop is the safer choice.
# ---------------------------------------------------------------------------
set -euo pipefail

SPOOL=${DGA_SPOOL:-/var/lib/dga-edge/spool}
OUT=${DGA_OUT:-/var/lib/dga-edge/out}
DONE=${DGA_DONE:-/var/lib/dga-edge/done}
POLL_SECONDS=${DGA_POLL_SECONDS:-5}
METHODS=${DGA_METHODS:-iec_three_ratio,iec_ratio,rogers_ratio,duval_triangle1}

mkdir -p "$SPOOL" "$OUT" "$DONE"

log() { printf '[dga-edge] %s\n' "$*"; }
log "watching ${SPOOL} every ${POLL_SECONDS}s -> ${OUT}"

while true; do
  shopt -s nullglob
  for input in "$SPOOL"/*.csv; do
    base="$(basename "$input" .csv)"
    stamp="$(date +%Y%m%dT%H%M%S)"
    log "processing ${base}"

    if python3 -m dga_service.cli \
        --input "$input" \
        --methods "$METHODS" \
        --output "${OUT}/${base}.${stamp}.csv" \
        --jsonl "${OUT}/${base}.${stamp}.jsonl" \
        >> "${OUT}/${base}.log" 2>&1
    then
      mv "$input" "${DONE}/${base}.${stamp}.csv"
      log "done ${base}"
    else
      mv "$input" "${DONE}/${base}.${stamp}.failed.csv"
      log "FAILED ${base} - see ${OUT}/${base}.log"
    fi
  done
  shopt -u nullglob
  sleep "$POLL_SECONDS"
done
