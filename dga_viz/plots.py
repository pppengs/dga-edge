# -*- coding: utf-8 -*-
"""dga_viz.plots

HOST-SIDE ONLY. Optional-dependency visualisation layer.

matplotlib must never be imported by dga_core or dga_service: those two
packages are what ships to the Jetson Nano, where matplotlib is both too large
and awkward to build for aarch64 / Python 3.6. Everything here is optional and
fails with a clear message rather than breaking the import of the core.

Run:  python -m dga_viz.plots
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "figures")

ZONE_COLORS = {
    "PD": "#8dd3c7", "T1": "#ffffb3", "T2": "#fb8072", "T3": "#80b1d3",
    "D1": "#fdb462", "D2": "#bebada", "DT": "#b3de69",
}


def _require_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        raise SystemExit(
            "matplotlib is not installed. It is an optional, host-side-only "
            "dependency: pip install matplotlib")


def _tri_xy(a, b, c):
    """Ternary (CH4, C2H2, C2H4) -> cartesian, matching dga_core."""
    import math
    total = a + b + c
    x = 0.5 * (2.0 * c + b) / total
    y = (math.sqrt(3.0) / 2.0) * b / total
    return x, y


def plot_duval(samples, labels=None, title="Duval Triangle 1", filename="duval_triangle1.png"):
    plt = _require_matplotlib()
    from dga_core.tables import DUVAL1_ZONES
    from dga_core.methods import _ternary_to_cartesian

    fig, ax = plt.subplots(figsize=(8, 7))
    for zone, pts in DUVAL1_ZONES.items():
        xy = [_ternary_to_cartesian(a, b, c) for (a, b, c) in pts]
        xs = [p[0] for p in xy] + [xy[0][0]]
        ys = [p[1] for p in xy] + [xy[0][1]]
        ax.fill(xs, ys, color=ZONE_COLORS.get(zone, "#cccccc"), alpha=0.55,
                edgecolor="#444444", linewidth=0.6)
        cx = sum(p[0] for p in xy) / len(xy)
        cy = sum(p[1] for p in xy) / len(xy)
        ax.text(cx, cy, zone, ha="center", va="center", fontsize=11, fontweight="bold")

    verts = [("CH4", (100, 0, 0)), ("C2H2", (0, 100, 0)), ("C2H4", (0, 0, 100))]
    for name, t in verts:
        x, y = _ternary_to_cartesian(*t)
        ax.plot([x], [y], "ko", markersize=4)
        ax.text(x, y + (0.045 if y < 0.5 else -0.055), name,
                ha="center", fontsize=12, fontweight="bold")

    if labels:
        groups = {}
        for s, lab in zip(samples, labels):
            if not lab:
                continue
            total = s.ch4 + s.c2h2 + s.c2h4
            if total <= 0:
                continue
            groups.setdefault(lab, []).append(_tri_xy(s.ch4, s.c2h2, s.c2h4))
        for lab, pts in sorted(groups.items()):
            ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=9, alpha=0.65, label=lab)
        ax.legend(fontsize=8, loc="upper right")

    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.08, 0.95)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=13)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def plot_method_comparison(summary_rows, filename="method_comparison.png"):
    """Grouped bars: decision rate, acc_of_decided, acc_of_all per method."""
    plt = _require_matplotlib()
    import numpy as np

    rows = [r for r in summary_rows if r.get("subset") == "all"]
    if not rows:
        raise SystemExit("no 'all' subset rows to plot")

    keys = [(r["dataset"], r["method"]) for r in rows]
    labels = ["{}\n{}".format(d, m) for d, m in keys]
    decision = [r["decision_rate_pct"] for r in rows]
    acc_dec = [r["acc_of_decided_pct"] for r in rows]
    acc_all = [r["acc_of_all_pct"] for r in rows]

    x = np.arange(len(labels))
    width = 0.27
    fig, ax = plt.subplots(figsize=(max(9, len(labels) * 1.5), 5))
    ax.bar(x - width, decision, width, label="decision rate", color="#378ADD")
    ax.bar(x, acc_dec, width, label="accuracy of decided", color="#1D9E75")
    ax.bar(x + width, acc_all, width, label="accuracy of all", color="#D85A30")
    ax.set_ylabel("%")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 105)
    ax.legend(fontsize=9)
    ax.set_title("Decision rate vs accuracy (undecided counted as wrong)", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def plot_confusion(conf, classes, title, filename):
    plt = _require_matplotlib()
    import numpy as np

    m = np.zeros((len(classes), len(classes)))
    for i, t in enumerate(classes):
        for j, p in enumerate(classes):
            m[i, j] = conf.get((t, p), 0)

    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    im = ax.imshow(m, cmap="Blues")
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(classes)
    ax.set_yticklabels(classes)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title, fontsize=11)
    thresh = m.max() * 0.6 if m.max() else 0
    for i in range(len(classes)):
        for j in range(len(classes)):
            v = int(m[i, j])
            if v:
                ax.text(j, i, v, ha="center", va="center", fontsize=9,
                        color="white" if m[i, j] > thresh else "black")
    fig.colorbar(im, ax=ax, shrink=0.8)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


CONDITION_COLORS = {1: "#4daf4a", 2: "#ffff33", 3: "#ff7f00", 4: "#e41a1c"}
CONDITION_NAMES = {1: "C1 Normal", 2: "C2 Investigate",
                   3: "C3 Warning", 4: "C4 Critical"}


def plot_condition_by_label(rows, filename="condition_by_label.png"):
    """Stacked bars: IEEE C57.104 condition distribution within each true class.

    :param rows: list of dicts with dataset/truth/n/cond_1..cond_4
    """
    plt = _require_matplotlib()

    datasets = []
    for r in rows:
        if r["dataset"] not in datasets:
            datasets.append(r["dataset"])

    fig, axes = plt.subplots(1, len(datasets),
                             figsize=(5.4 * len(datasets), 4.2), squeeze=False)
    for ax, ds in zip(axes[0], datasets):
        sub = [r for r in rows if r["dataset"] == ds]
        sub = sorted(sub, key=lambda r: -float(r["mean_condition"]))
        truths = [r["truth"] for r in sub]
        left = [0] * len(sub)
        for level in (1, 2, 3, 4):
            vals = [int(r["cond_" + str(level)]) for r in sub]
            ax.barh(range(len(sub)), vals, left=left, color=CONDITION_COLORS[level],
                    label=CONDITION_NAMES[level], edgecolor="white", linewidth=0.5)
            left = [a + b for a, b in zip(left, vals)]
        ax.set_yticks(range(len(sub)))
        ax.set_yticklabels(truths)
        ax.invert_yaxis()
        ax.set_xlabel("samples")
        ax.set_title("{} - condition by true class".format(ds), fontsize=11)
        for i, r in enumerate(sub):
            ax.text(left[i] + 1, i, "mean {:.2f}".format(float(r["mean_condition"])),
                    va="center", fontsize=8)
    axes[0][0].legend(loc="lower right", fontsize=8)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def main():
    from experiments.loaders import DATASETS
    from dga_core import DEFAULT_METHODS, assess_condition
    from dga_service.pipeline import run_batch
    import csv as _csv

    paths = []
    confusions = {}
    all_cond_rows = []
    for name, loader in DATASETS.items():
        labelled = [(s, t) for s, t in loader() if t]
        samples = [s for s, _ in labelled]
        labels = [t for _, t in labelled]
        paths.append(plot_duval(
            samples, labels,
            title="Duval Triangle 1 - {}".format(name),
            filename="duval_{}.png".format(name)))
        print("wrote duval_{}.png".format(name))

        # Confusion matrix for the best-deciding method on this dataset.
        truth = dict((s.sample_id, t) for s, t in labelled)
        report = run_batch(samples, methods=DEFAULT_METHODS, with_condition=False)
        classes = sorted(set(truth.values()))
        for m in DEFAULT_METHODS:
            conf = {}
            for res in report.results:
                t = truth.get(res.sample_id)
                if not t:
                    continue
                for mr in res.results:
                    if mr.method == m and mr.applicable and mr.code not in ("ND", "N/A", "-"):
                        conf[(t, mr.code)] = conf.get((t, mr.code), 0) + 1
            if conf:
                confusions[(name, m)] = conf
        # Only render the two most decisive methods, to keep the figure count sane
        for m in ("duval_triangle1", "iec_three_ratio"):
            conf = confusions.get((name, m))
            if conf:
                fn = "confusion_{}_{}.png".format(name, m)
                paths.append(plot_confusion(
                    conf, classes,
                    "{} - {}".format(name, m), fn))
                print("wrote {}".format(fn))

        # Condition distribution per true class (accumulated across datasets)
        by_label = {}
        for s, t in labelled:
            by_label.setdefault(t, []).append(assess_condition(s).condition)
        for t, vals in by_label.items():
            row = {"dataset": name, "truth": t, "n": len(vals),
                   "mean_condition": sum(vals) / float(len(vals))}
            for level in (1, 2, 3, 4):
                row["cond_" + str(level)] = sum(1 for v in vals if v == level)
            all_cond_rows.append(row)

    summary_path = os.path.join(ROOT, "experiments", "results", "summary.csv")
    rows = []
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as fh:
            rows = [dict(r) for r in _csv.DictReader(fh)]
        for r in rows:
            for k in ("n_total", "n_decided"):
                r[k] = int(r[k])
            for k in ("decision_rate_pct", "acc_of_decided_pct", "acc_of_all_pct", "macro_f1"):
                r[k] = float(r[k])
        paths.append(plot_method_comparison(rows))
        print("wrote method_comparison.png")

    if all_cond_rows:
        paths.append(plot_condition_by_label(all_cond_rows))
        print("wrote condition_by_label.png")

    print("\nfigures in {}".format(OUT))
    for p in paths:
        print("  {}".format(p))


if __name__ == "__main__":
    main()
