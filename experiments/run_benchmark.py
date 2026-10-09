# -*- coding: utf-8 -*-
"""experiments.run_benchmark

Latency / throughput / memory benchmark. Runs anywhere Python 3.6+ runs, so the
identical script produces both the host (x86) and the target (Jetson Nano)
numbers, which makes the platform comparison apples-to-apples.

Writes experiments/results/benchmark_<tag>.csv and prints a summary.

Usage:
    python experiments/run_benchmark.py --tag host-x86
    python experiments/run_benchmark.py --tag jetson-nano-10w --repeats 5000
"""

import argparse
import csv
import os
import platform
import sys
import time
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from dga_core import GasSample, diagnose, DEFAULT_METHODS  # noqa: E402

OUT = os.path.join(HERE, "results")

# A representative sample: thermal fault with a meaningful C2H2 level.
REFERENCE = GasSample(h2=100.0, ch4=200.0, c2h6=50.0, c2h4=100.0, c2h2=1.0,
                      sample_id="bench")


def percentile(sorted_values, q):
    if not sorted_values:
        return float("nan")
    idx = int(q * len(sorted_values) + 0.9999) - 1
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]


def bench_latency(repeats):
    for _ in range(max(500, repeats // 10)):
        diagnose(REFERENCE)
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        diagnose(REFERENCE)
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1e6)
    samples.sort()
    mean = sum(samples) / len(samples)
    return {
        "p50_us": percentile(samples, 0.50),
        "p95_us": percentile(samples, 0.95),
        "p99_us": percentile(samples, 0.99),
        "mean_us": mean,
        "min_us": samples[0],
        "max_us": samples[-1],
        "repeats": repeats,
    }


def bench_per_method(repeats):
    from dga_core import METHOD_REGISTRY, compute_ratios
    out = {}
    ratios = compute_ratios(REFERENCE)
    for name in DEFAULT_METHODS:
        fn = METHOD_REGISTRY[name]
        for _ in range(200):
            fn(REFERENCE, ratios) if name != "duval_triangle1" else fn(REFERENCE)
        t0 = time.perf_counter()
        for _ in range(repeats):
            if name == "duval_triangle1":
                fn(REFERENCE)
            else:
                fn(REFERENCE, ratios)
        t1 = time.perf_counter()
        out[name] = (t1 - t0) / repeats * 1e6
    return out


def bench_throughput(rounds, batch=200):
    """Simulate N distinct samples so caches cannot flatter the result."""
    population = []
    for i in range(batch):
        population.append(GasSample(
            h2=50.0 + i, ch4=100.0 + i * 0.7, c2h6=30.0 + i * 0.3,
            c2h4=60.0 + i * 0.5, c2h2=0.5 + i * 0.01,
            sample_id="s{:04d}".format(i)))

    best = float("inf")
    for _ in range(rounds):
        t0 = time.perf_counter()
        for s in population:
            diagnose(s)
        t1 = time.perf_counter()
        best = min(best, t1 - t0)
    return {
        "batch_size": batch,
        "best_wall_s": best,
        "samples_per_s": batch / best,
        "us_per_sample": best / batch * 1e6,
    }


def bench_memory(batch=200):
    population = [GasSample(h2=50.0 + i, ch4=100.0, c2h6=30.0, c2h4=60.0,
                            c2h2=1.0, sample_id=str(i)) for i in range(batch)]
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    for s in population:
        diagnose(s)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "retained_bytes_per_sample": (current - base) / batch,
        "retained_bytes_total": current - base,
        "peak_bytes": peak,
    }


def bench_import():
    """Cold import cost, measured in a fresh interpreter where possible."""
    import subprocess
    code = "import time,sys;t=time.perf_counter();import dga_core;print((time.perf_counter()-t)*1000)"
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        out = subprocess.check_output([sys.executable, "-c", code], env=env,
                                      stderr=subprocess.DEVNULL)
        return float(out.strip())
    except Exception:
        return float("nan")


def runtime_footprint():
    """How much of the process is our code vs the interpreter's own baseline."""
    import resource
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        rss_kb = rss_kb / 1024.0     # macOS reports bytes
    return rss_kb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="host", help="label for this run")
    parser.add_argument("--repeats", type=int, default=20000)
    parser.add_argument("--rounds", type=int, default=50)
    args = parser.parse_args()

    os.makedirs(OUT, exist_ok=True)

    print("=" * 68)
    print("dga-edge benchmark   tag={}   python={}   platform={}".format(
        args.tag, sys.version.split()[0], platform.platform()))
    print("=" * 68)

    imp = bench_import()
    lat = bench_latency(args.repeats)
    per_method = bench_per_method(max(2000, args.repeats // 4))
    thr = bench_throughput(args.rounds)
    mem = bench_memory()

    print("")
    print("import (cold)      : {:8.2f} ms".format(imp))
    print("latency all methods: P50 {:7.2f} us | P95 {:7.2f} us | P99 {:7.2f} us".format(
        lat["p50_us"], lat["p95_us"], lat["p99_us"]))
    print("throughput         : {:,.0f} samples/s ({} in {:.4f} s)".format(
        thr["samples_per_s"], thr["batch_size"], thr["best_wall_s"]))
    print("memory             : {:,.0f} bytes retained per sample, peak {:.1f} KB".format(
        mem["retained_bytes_per_sample"], mem["peak_bytes"] / 1024.0))
    print("")
    print("per-method mean latency (us):")
    for name in DEFAULT_METHODS:
        print("    {:<18} {:8.2f}".format(name, per_method[name]))

    try:
        rss = runtime_footprint()
        print("")
        print("process peak RSS   : {:,.0f} KB".format(rss))
    except Exception:
        rss = float("nan")

    rows = [
        ("tag", args.tag),
        ("python", sys.version.split()[0]),
        ("platform", platform.platform()),
        ("machine", platform.machine()),
        ("import_cold_ms", round(imp, 4)),
        ("latency_p50_us", round(lat["p50_us"], 3)),
        ("latency_p95_us", round(lat["p95_us"], 3)),
        ("latency_p99_us", round(lat["p99_us"], 3)),
        ("latency_mean_us", round(lat["mean_us"], 3)),
        ("latency_repeats", lat["repeats"]),
        ("throughput_samples_per_s", round(thr["samples_per_s"], 1)),
        ("throughput_us_per_sample", round(thr["us_per_sample"], 3)),
        ("retained_bytes_per_sample", round(mem["retained_bytes_per_sample"], 2)),
        ("heap_peak_bytes", mem["peak_bytes"]),
        ("process_peak_rss_kb", round(rss, 1)),
    ]
    for name in DEFAULT_METHODS:
        rows.append(("mean_us_" + name, round(per_method[name], 3)))

    path = os.path.join(OUT, "benchmark_{}.csv".format(args.tag))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerows(rows)
    print("")
    print("wrote {}".format(path))


if __name__ == "__main__":
    main()
