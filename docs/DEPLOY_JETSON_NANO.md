# Deploying on Jetson Nano

Target: **Jetson Nano (2019) 4 GB, JetPack 4.6.4 / L4T r32.7.4, Ubuntu 18.04,
Python 3.6, aarch64.**

The same zero-dependency kernel also runs unchanged on Jetson Orin Nano
(JetPack 6.x / Python 3.10), Raspberry Pi, and x86 — nothing here is
Nano-specific except the power-mode and swap steps.

> Scope note: this repository delivers **adaptation**, not a commissioned
> installation. No physical board or transformer is required to reproduce
> anything described below; the deployment scripts and the compatibility
> checker together stand in for a board in CI.

---

## 1. Why this platform

Jetson Nano (2019) is the most constrained target in the family:

| Constraint | Value | Consequence |
|---|---|---|
| JetPack ceiling | **4.6.4** — JetPack 5/6 do not support this board | pins the whole toolchain |
| Python | **3.6** | no `dataclasses`, no walrus, no builtin generics |
| pip wheels for aarch64 + py3.6 | numpy must be pinned to 1.19.x; pandas and matplotlib frequently have no wheel | **hence zero dependencies in the kernel** |
| RAM | 4 GB, 5 W default mode | swap extension + 10 W mode |
| GPU | 128-core Maxwell | **not used, and not needed** |

Targeting the hardest platform means one codebase covers every other one. The
decision is recorded in the feasibility document; the point of restating it here
is that the constraints above are the *reason* for the architecture, not a
limitation discovered afterwards.

**The GPU genuinely goes unused.** Classical DGA interpretation is a handful of
divisions, two table lookups and one point-in-polygon test. There is nothing to
accelerate. The measured per-sample cost is in the tens of microseconds on a
Cortex-A57 — see `experiments/results/`.

---

## 2. What actually gets installed

```
dga_core/      zero-dependency diagnosis + condition kernel   ~39 KB
dga_service/   batch pipeline, CSV/JSONL I/O, CLI, trend       ~20 KB
```

Within `dga_core`, the split is roughly:

| File | Purpose | Size |
|---|---|---|
| `tables.py` | every threshold table, with provenance comments | ~9 KB |
| `methods.py` | ratio computation + the five diagnostic methods | ~12 KB |
| `condition.py` | IEEE C57.104-2019 grading, gas rate, sampling advice | ~11 KB |
| `validation.py` | input validation, sentinel-zero detection | ~3 KB |
| `models.py` | plain-data containers (`typing.NamedTuple`) | ~2 KB |

`condition.py` costs the board about 11 KB of source and no dependencies. The
entire condition assessment is scalar arithmetic, so it adds nothing measurable
to per-sample latency - the 2000-sample benchmark in
`experiments/results/benchmark_*.csv` reports methods and condition together.

Explicitly **not** deployed:

| Package | Why excluded |
|---|---|
| numpy | not needed; pinned-version trap on aarch64/py3.6 |
| pandas | no reliable wheel; `csv` in the stdlib covers the need |
| matplotlib | large, slow to import, plotting belongs on the host |
| openpyxl | only used by `experiments/loaders.py` to read `.xlsx` datasets |
| scikit-learn / xgboost | out of scope — this project is classical methods only |

`tools/check_py36_compat.py` enforces the Python 3.6 grammar constraint, and
`tests/test_dga_core.py::TestZeroDependency` fails the build if a banned module
gets imported. Those two checks are the CI substitute for owning a board.

---

## 3. Prepare the board

```bash
git clone <your-fork> dga-edge
cd dga-edge/deployment/jetson-nano
sudo ./setup.sh
```

`setup.sh` performs, idempotently:

1. **Platform check** — verifies aarch64, reads `/etc/nv_tegra_release`, reports
   the Python version and warns if it is not 3.6.
2. **Swap extension** — creates a 4 GB swapfile at `/var/swapfile-dga` and adds
   it to `/etc/fstab`. 4 GB of RAM is tight once dataset files and logs are in
   play.
3. **Power mode** — `nvpmodel -m 0` (10 W) plus `jetson_clocks`. Skip with
   `--no-nvpmodel`. If you are not on the barrel-jack supply, 10 W mode may
   brown out; the script warns rather than failing.
4. **System packages only** — `python3-minimal`, `ca-certificates`. No pip
   wheels, by design.
5. **Application install** — `pip install --no-deps .`, with an automatic
   fallback to a `PYTHONPATH` install at `/opt/dga-edge` for the older pip that
   ships with JetPack 4.6.4.
6. **Verification** — runs a diagnosis in a clean interpreter, prints which of
   numpy/pandas/matplotlib are absent, and reports the result.

---

## 4. Run modes

### Batch (one-shot)

```bash
python3 -m dga_service.cli \
    --input  samples.csv \
    --output results.csv \
    --jsonl  results.jsonl
```

Input CSV columns are matched by alias, so utility exports work directly:
`H2/hydrogen/氢气`, `CH4/methane/甲烷`, `C2H6/ethane/乙烷`, `C2H4/ethylene/乙烯`,
`C2H2/acetylene/乙炔`. An optional id column (`id`, `sample_id`, `组号`, `...`) is
carried through to the output. Each row additionally gets the IEEE C57.104
condition columns (`condition`, `condition_label`, `tdcg`, `limiting_gas`,
`sampling_interval`); disable with `--no-condition`.

### Trend mode (time series)

If the export carries dates, drop `--trend` and the CLI groups rows by unit id,
orders them by date, and evaluates the gas generation rate of the latest sample
against the previous one:

```bash
python3 -m dga_service.cli \
    --input examples/samples_timeseries.csv \
    --trend --output trend.csv
```

Output gains `rate_significant`, `interval_days`, and `rate_gases_t3` /
`rate_gases_t4` (the gases that tripped the IEEE C57.104 Table 3 / Table 4
limits). A significant rate raises the condition by at most one level. Rows
without a parseable date are reported and excluded rather than silently treated
as zero-interval, because a rate of change without an interval is meaningless.

`--o2n2 0.5` selects the high-O₂/N₂ table columns; the default is the
low-O₂/N₂ (sealed-unit) column, which is the conservative choice.

### Watch mode (spool directory)

```bash
sudo install -m 0644 dga-monitor.service /etc/systemd/system/
sudo mkdir -p /var/lib/dga-edge/{spool,out,done}
sudo systemctl daemon-reload
sudo systemctl enable --now dga-monitor
```

Drop a CSV into `/var/lib/dga-edge/spool/`; the watcher diagnoses it and writes
`<name>.<timestamp>.csv` and `.jsonl` into `out/`, then moves the input to
`done/`. It uses a poll loop rather than `inotify` so that it depends on nothing
beyond the standard Ubuntu 18.04 packages.

The unit applies `MemoryMax=256M`, `CPUQuota=50%` and `TasksMax=16`. The kernel
itself needs a few hundred kilobytes per diagnosis; the headroom exists for the
interpreter and logging, and the quota keeps the diagnosis job from competing
with anything else on the board.

---

## 5. Measuring on the board

```bash
./tegrastats_collect.sh /var/log/dga-edge/tegrastats.log \
    -- python3 experiments/run_benchmark.py --tag jetson-nano-10w
```

`experiments/run_benchmark.py` is platform-agnostic on purpose: the identical
script and flags produce the host numbers, so the comparison is
apples-to-apples. It reports cold import, latency percentiles, per-method mean
latency, throughput and heap retention, and writes
`experiments/results/benchmark_<tag>.csv`.

Warning: Python 3.6's `datetime`-based `perf_counter` is fine, but the
interpreter itself is roughly 2–4× slower per bytecode op than 3.13. Expect the
latency figures to be worse than the host run for reasons that have nothing to
do with the algorithm. Report interpreter version alongside every number.

---

## 6. Expected results

Reference figures measured on the host (CPython 3.13, x86) are in the
feasibility document, appendix A. The short version:

| Quantity | Host measured |
|---|---|
| Kernel source | ~20 KB, 6 files |
| Runtime "model" | 0.9 KB (Duval zones: 40 vertices) |
| Third-party dependencies | 0 |
| Latency, all methods | P50 ~12 µs, P99 ~27 µs |
| Throughput | ~87,000 samples/s |
| Heap retained per sample | ≈ 0 bytes |

A 100-transformer fleet polled at 1 Hz needs 100 samples/s. Even a pessimistic
10× derating for the Cortex-A57 leaves roughly two orders of magnitude of
headroom. **The diagnosis step is not the bottleneck on this platform, and no
amount of optimisation will change what is measured: the cost is dominated by
the Python interpreter, not by the algorithm.**

If you need to go faster, the lever is not vectorising the arithmetic — it is
avoiding interpreter overhead (process the batch in one process, avoid re-import,
stream CSV rather than building lists).

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pip install` fails on old pip | JetPack 4.6.4 ships an old pip | `setup.sh` already falls back to a PYTHONPATH install |
| `nvpmodel -m 0` fails | board not jumpered for barrel jack, or on USB power | fit J48, use the 5 V/4 A supply |
| `ModuleNotFoundError: numpy` | something imported an optional module | check `tools/check_py36_compat.py` and the zero-dependency test |
| Diagnosis returns mostly `N/A` | input columns not recognised, or values are all zero | run with the header printed; check for a duplicated header row (the Cliango dataset has one) |
| Diagnosis returns many `ND` | normal for IEC/Rogers on sparse data | report `decision_rate` alongside accuracy; see `docs/STANDARDS.md` |
| Downloading datasets fails with SSL errors | upstream CDN drops scripted clients intermittently | retry `scripts/fetch_datasets.py` |

---

## 8. Uninstall

```bash
sudo systemctl disable --now dga-monitor
sudo rm -f /etc/systemd/system/dga-monitor.service
sudo rm -rf /opt/dga-edge /var/lib/dga-edge
sudo swapoff /var/swapfile-dga && sudo rm -f /var/swapfile-dga
# remove the /etc/fstab line added by setup.sh
```
