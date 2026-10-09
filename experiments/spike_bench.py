# -*- coding: utf-8 -*-
"""experiments.spike_bench - feasibility spike: how big and how fast is the kernel?

Host-side benchmark harness. It measures the things that decide whether the
kernel can live on a Jetson Nano:

  1. code size on disk (LOC / bytes)
  2. import cost
  3. single-sample diagnosis latency (P50 / P95 / P99)
  4. batch throughput on a real 589-sample dataset
  5. Python heap allocated per diagnosis
  6. dependency audit - proves nothing outside the stdlib got pulled in

Run:  python -m experiments.spike_bench
"""

import os
import sys
import time
import math
import statistics
import tracemalloc
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

CACHE = os.path.join(ROOT, ".cache")
DATASET_URL = "https://raw.githubusercontent.com/alan-456/transformer-fault-dataset/main/dataset_(589).xlsx"
DATASET_PATH = os.path.join(CACHE, "a589.xlsx")


# --------------------------------------------------------------------------
# 0. dependency audit
# --------------------------------------------------------------------------

def audit_dependencies():
    print("\n[0] Dependency audit")
    before = set(sys.modules)
    import dga_core  # noqa: F401
    new = sorted(m for m in (set(sys.modules) - before) if "." not in m)
    third_party = [m for m in new if m not in sys.stdlib_module_names] if hasattr(
        sys, "stdlib_module_names") else []
    print("    modules pulled in by 'import dga_core': {}".format(new))
    print("    non-stdlib modules: {}".format(third_party if third_party else "NONE"))
    return third_party


# --------------------------------------------------------------------------
# 1. code size
# --------------------------------------------------------------------------

def measure_code_size():
    print("\n[1] Code size (dga_core/, stdlib only)")
    total_bytes = 0
    total_lines = 0
    for root, _dirs, files in os.walk(os.path.join(ROOT, "dga_core")):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            with open(p, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            n_bytes = os.path.getsize(p)
            n_code = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
            total_bytes += n_bytes
            total_lines += len(lines)
            print("    {:<22} {:>6} bytes  {:>4} lines  ({:>4} code)".format(
                fn, n_bytes, len(lines), n_code))
    print("    {:<22} {:>6} bytes  {:>4} lines".format("TOTAL", total_bytes, total_lines))
    return total_bytes, total_lines


def measure_table_size():
    print("\n[1b] Runtime 'model' size")
    import dga_core
    from dga_core.tables import DUVAL1_ZONES
    n_pts = sum(len(v) for v in DUVAL1_ZONES.values())
    n_floats = n_pts * 3
    print("    Duval Triangle 1: {} zones, {} vertices, {} numbers".format(
        len(DUVAL1_ZONES), n_pts, n_floats))
    print("    -> {:.1f} KB of float data held in RAM".format(n_floats * 8 / 1024.0))
    return n_floats


# --------------------------------------------------------------------------
# 2. import cost
# --------------------------------------------------------------------------

def measure_import_time():
    print("\n[2] Import cost (cold, subprocess-free estimate)")
    t0 = time.perf_counter()
    for mod in [m for m in list(sys.modules) if m.startswith("dga_core")]:
        del sys.modules[mod]
    import dga_core  # noqa: F401
    t1 = time.perf_counter()
    print("    re-import dga_core: {:.3f} ms".format((t1 - t0) * 1000))
    return (t1 - t0) * 1000


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------

def fetch_dataset():
    if not os.path.exists(DATASET_PATH):
        os.makedirs(CACHE, exist_ok=True)
        print("\n[3] Downloading dataset -> {}".format(DATASET_PATH))
        urllib.request.urlretrieve(DATASET_URL, DATASET_PATH)
    return DATASET_PATH


def load_samples(path):
    """Host-side only: openpyxl is NOT a dependency of dga_core."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.values)
    wb.close()
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}

    from dga_core import GasSample
    out = []
    for r_i, r in enumerate(rows[1:]):
        if r[idx["H2"]] is None:
            continue
        out.append(GasSample(
            h2=float(r[idx["H2"]]),
            ch4=float(r[idx["CH4"]]),
            c2h6=float(r[idx["C2H6"]]),
            c2h4=float(r[idx["C2H4"]]),
            c2h2=float(r[idx["C2H2"]]),
            sample_id="{:04d}".format(r_i),
        ))
    return out, header


# --------------------------------------------------------------------------
# 3/4. latency & throughput
# --------------------------------------------------------------------------

def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    k = int(math.ceil(q * len(sorted_vals))) - 1
    k = max(0, min(k, len(sorted_vals) - 1))
    return sorted_vals[k]


def measure_latency(samples, repeats=20000):
    from dga_core import diagnose
    s = samples[0]

    # warm up
    for _ in range(2000):
        diagnose(s)

    lat = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        diagnose(s)
        t1 = time.perf_counter()
        lat.append((t1 - t0) * 1e6)  # microseconds
    lat.sort()

    print("\n[4] Single-sample latency ({} iterations, all 3 methods)".format(repeats))
    print("    P50   {:8.1f} us".format(pct(lat, 0.50)))
    print("    P95   {:8.1f} us".format(pct(lat, 0.95)))
    print("    P99   {:8.1f} us".format(pct(lat, 0.99)))
    print("    mean  {:8.1f} us".format(statistics.fmean(lat) if hasattr(
        statistics, "fmean") else statistics.mean(lat)))
    return pct(lat, 0.50), pct(lat, 0.95), pct(lat, 0.99)


def measure_throughput(samples, rounds=20):
    from dga_core import diagnose
    n = len(samples)
    best = float("inf")
    for _ in range(rounds):
        t0 = time.perf_counter()
        for s in samples:
            diagnose(s)
        t1 = time.perf_counter()
        best = min(best, t1 - t0)
    rate = n / best
    print("\n[5] Batch throughput ({} real samples, best of {})".format(n, rounds))
    print("    wall      {:.4f} s".format(best))
    print("    rate      {:,.0f} samples/s".format(rate))
    print("    per-sample{:8.2f} us".format(best / n * 1e6))
    return rate


def measure_heap(samples):
    from dga_core import diagnose
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    for s in samples[:200]:
        diagnose(s)
    cur = tracemalloc.get_traced_memory()[0]
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print("\n[6] Python heap allocated by diagnosis")
    print("    steady-state delta over 200 samples: {:,.0f} bytes ({:.1f} KB)".format(
        cur - base, (cur - base) / 1024.0))
    print("    per-sample retained (should be ~0):  {:.0f} bytes".format(
        (cur - base) / 200.0))
    print("    peak during run:                     {:.1f} KB".format(peak / 1024.0))
    return (cur - base) / 200.0


# --------------------------------------------------------------------------
# 7. sanity: does it actually produce sensible zone distributions?
# --------------------------------------------------------------------------

def sanity(samples):
    from dga_core import diagnose
    from collections import Counter
    print("\n[7] Sanity check on {} real samples".format(len(samples)))
    counters = {}
    flagged = 0
    for s in samples:
        res = diagnose(s)
        if any(v is not None and 0 < v < 1e-3 for v in
               (s.h2, s.ch4, s.c2h6, s.c2h4, s.c2h2)):
            flagged += 1
        for m in res.results:
            counters.setdefault(m.method, Counter())[m.code] += 1
    for name, c in sorted(counters.items()):
        total = sum(c.values())
        parts = "  ".join("{}={}".format(k, v) for k, v in c.most_common())
        decided = total - c.get("ND", 0) - c.get("N/A", 0)
        print("    {:<16} {}".format(name, parts))
        print("    {:<16} decided {}/{} = {:.1f}%".format(
            "", decided, total, 100.0 * decided / total))
    print("\n    samples containing sub-1e-3 sentinel values: {} ({:.1f}%)".format(
        flagged, 100.0 * flagged / len(samples)))
    return counters


# --------------------------------------------------------------------------
# 8. Jetson Nano projection
# --------------------------------------------------------------------------

def project_jetson(p50_us, p99_us, rate):
    print("\n[8] Jetson Nano projection (ESTIMATE, not measured)")
    print("    Cortex-A57 @1.43 GHz vs this host: assume 6x-10x slower single-thread")
    for f in (6, 8, 10):
        print("    x{:<2}  P50 {:7.1f} us   P99 {:7.1f} us   {:>8,.0f} samples/s".format(
            f, p50_us * f, p99_us * f, rate / f))
    print("    reference: a 1 Hz monitoring loop needs 1 sample/s;")
    print("               a 100-transformer fleet at 1 Hz needs 100 samples/s.")


def main():
    print("=" * 72)
    print("DGA embedded feasibility spike")
    print("python {} on {}".format(sys.version.split()[0], sys.platform))
    print("=" * 72)

    audit_dependencies()
    measure_code_size()
    measure_table_size()
    measure_import_time()

    path = fetch_dataset()
    samples, header = load_samples(path)
    print("\n[3] Dataset loaded: {} samples, header={}".format(len(samples), header))

    p50, p95, p99 = measure_latency(samples)
    rate = measure_throughput(samples)
    measure_heap(samples)
    sanity(samples)
    project_jetson(p50, p99, rate)

    print("\n" + "=" * 72)
    print("Spike complete.")
    print("=" * 72)


if __name__ == "__main__":
    main()
