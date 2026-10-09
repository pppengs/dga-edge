#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dga-edge :: tegrastats sampler
#
# Captures tegrastats output around a workload so that resource claims in the
# report can be traced back to raw logs rather than asserted.
#
# Usage:
#   ./tegrastats_collect.sh out/tegrastats.log -- python3 experiments/run_benchmark.py
# ---------------------------------------------------------------------------
set -euo pipefail

INTERVAL_MS=${TEGRASTATS_INTERVAL_MS:-500}
LOG=${1:?usage: $0 <logfile> [-- command...]}
shift
[ "${1:-}" = "--" ] && shift

if ! command -v tegrastats >/dev/null 2>&1; then
  echo "tegrastats not found - this script only works on a Jetson board." >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG")"
echo "# tegrastats @ ${INTERVAL_MS}ms  $(date -Is)" > "$LOG"

tegrastats --interval "$INTERVAL_MS" >> "$LOG" 2>&1 &
SAMPLER=$!
# shellcheck disable=SC2064
trap "kill ${SAMPLER} 2>/dev/null || true" EXIT

echo "# workload: $*" >> "$LOG"
"$@" || echo "# workload exited with $?" >> "$LOG"

kill "$SAMPLER" 2>/dev/null || true
wait "$SAMPLER" 2>/dev/null || true
echo "# finished $(date -Is)" >> "$LOG"

echo "wrote $LOG"
