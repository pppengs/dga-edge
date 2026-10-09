#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dga-edge :: Jetson Nano deployment preparation
#
# Target platform: Jetson Nano (2019, 4GB/2GB) - JetPack 4.6.4 / L4T r32.7.4
#                  Ubuntu 18.04, Python 3.6, aarch64
#
# This script performs ADAPTATION ONLY. It prepares the board and installs the
# diagnosis kernel. It does not touch a real transformer or any SCADA system.
#
# Usage:
#   sudo ./setup.sh                 # prepare board + install
#   sudo ./setup.sh --no-nvpmodel   # skip the 10W power-mode switch
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SWAPFILE=/var/swapfile-dga
SWAP_SIZE_MB=4096
SKIP_NVPMODEL=0

for arg in "$@"; do
  case "$arg" in
    --no-nvpmodel) SKIP_NVPMODEL=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
  esac
done

log()  { printf '\033[1;34m[dga-edge]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dga-edge]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[dga-edge]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "run with sudo"
}

check_platform() {
  log "checking platform"
  [ "$(uname -m)" = "aarch64" ] || die "expected aarch64, got $(uname -m)"

  if [ -r /etc/nv_tegra_release ]; then
    local rel
    rel="$(head -n1 /etc/nv_tegra_release)"
    log "L4T: ${rel}"
    case "$rel" in
      *R32*) log "Jetson Nano / JetPack 4.x line detected - OK" ;;
      *) warn "this script targets L4T R32 (JetPack 4.6.x); continuing anyway" ;;
    esac
  else
    warn "/etc/nv_tegra_release not found - not a Jetson board?"
  fi

  local py
  py="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  log "python3: ${py}"
  case "$py" in
    3.6) log "Python 3.6 matches JetPack 4.6.4 - OK" ;;
    *) warn "expected Python 3.6, found ${py}; the core is 3.6-compatible but \
this board is not the target configuration" ;;
  esac
}

grow_swap() {
  # 4GB RAM is tight for dataset files and logging; upstream guidance is to
  # extend swap. Idempotent: safe to re-run.
  if swapon --show | grep -q "${SWAPFILE}"; then
    log "swap already active at ${SWAPFILE}"
    return
  fi
  log "creating ${SWAP_SIZE_MB}MB swap at ${SWAPFILE}"
  fallocate -l "${SWAP_SIZE_MB}M" "${SWAPFILE}" || dd if=/dev/zero of="${SWAPFILE}" bs=1M count="${SWAP_SIZE_MB}"
  chmod 600 "${SWAPFILE}"
  mkswap "${SWAPFILE}"
  swapon "${SWAPFILE}"
  grep -q "${SWAPFILE}" /etc/fstab || echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
  log "swap enabled"
}

set_power_mode() {
  if [ "${SKIP_NVPMODEL}" -eq 1 ]; then
    log "skipping power mode change (--no-nvpmodel)"
    return
  fi
  if command -v nvpmodel >/dev/null 2>&1; then
    log "switching to 10W mode (nvpmodel -m 0) and locking clocks"
    nvpmodel -m 0 || warn "nvpmodel failed; check the barrel-jack jumper (J48)"
    jetson_clocks || warn "jetson_clocks failed"
  else
    warn "nvpmodel not found; skipping"
  fi
}

install_packages() {
  log "installing runtime dependencies (system packages, NOT pip wheels)"
  # Deliberately empty of numpy/pandas/matplotlib: the kernel needs none of
  # them, and on aarch64 + Python 3.6 they either have no wheel or must be
  # compiled for a long time.
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends python3-minimal ca-certificates
}

install_application() {
  log "installing dga-edge (no dependencies by design)"
  cd "${PROJECT_ROOT}"
  python3 -m pip install --no-deps --no-build-isolation . 2>/dev/null || {
    # pip on JetPack 4.6.4 can be old; fall back to a path install.
    warn "pip install failed - falling back to PYTHONPATH deployment"
    local target=/opt/dga-edge
    rm -rf "${target}"
    mkdir -p "${target}"
    cp -r dga_core dga_service "${target}/"
    cat > /etc/profile.d/dga-edge.sh <<EOF
export PYTHONPATH="\${PYTHONPATH:-}:${target}"
EOF
    chmod 0644 /etc/profile.d/dga-edge.sh
    log "installed to ${target} (exported via /etc/profile.d/dga-edge.sh)"
    return
  }
  log "installed as a Python package"
}

verify() {
  log "verifying the install"
  cd /
  python3 - <<'PY'
import sys
from dga_core import GasSample, diagnose, monitor
s = GasSample(h2=100.0, ch4=200.0, c2h6=50.0, c2h4=100.0, c2h2=1.0, co=120.0)
res = diagnose(s)
status = monitor(s)
print("python            :", sys.version.split()[0])
print("third-party loaded:", sorted(
    m for m in sys.modules
    if m.split(".")[0] in {"numpy", "pandas", "matplotlib", "scipy"}) or "NONE")
for m in res.results:
    print("  {:<17} {} {}".format(m.method, m.code, "(decided)" if m.applicable else "(no decision)"))
print("condition         : C{} {} (TDCG {} ppm, limiting gas {})".format(
    status.condition, status.label, status.assessment.tdcg,
    status.assessment.limiting_gas or "none"))
PY
}

verify_third_party_absent() {
  log "confirming numpy/pandas/matplotlib are NOT present"
  python3 - <<'PY' || true
import importlib
for name in ("numpy", "pandas", "matplotlib"):
    try:
        importlib.import_module(name)
        print("present:", name)
    except ImportError:
        print("absent :", name, "(expected)")
PY
}

main() {
  require_root
  check_platform
  grow_swap
  set_power_mode
  install_packages
  install_application
  verify_third_party_absent
  verify
  log "done. Next: install the systemd unit (see docs/DEPLOY_JETSON_NANO.md)"
}

main "$@"
