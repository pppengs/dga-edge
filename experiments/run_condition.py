# -*- coding: utf-8 -*-
"""experiments.run_condition

Does IEEE C57.104-2019 condition grading actually separate healthy units from
faulted ones?

This is a different question from the one run_validation.py asks. The ratio
methods answer "which fault is it?"; the Table 1 condition grading answers
"is anything wrong at all?". The second question is the one an online monitor
has to answer first, and it is measurable on real labelled data:

    * treat "condition >= 2" as an alarm
    * score that alarm against the dataset's Normal / fault label

Produces:
    experiments/results/condition_summary.csv
    experiments/results/condition_by_label.csv
    experiments/results/CONDITION_REPORT.md

Host-side only (needs openpyxl to read the raw datasets).
"""

import os
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from dga_core import (  # noqa: E402
    assess_condition, diagnose, DEFAULT_METHODS, GasSample,
)
from dga_service.io_utils import write_csv  # noqa: E402
from experiments.loaders import DATASETS  # noqa: E402

OUT = os.path.join(HERE, "results")
CONDITIONS = (1, 2, 3, 4)
ALARM_AT = 2   # condition >= 2 raises the alarm

# Codes that mean "this method declined to name a fault". Anything not in here
# is treated as the method asserting a fault, i.e. an alarm.
NON_ALARM_CODES = frozenset(("ND", "N/A", "-", "", "Normal", "No fault"))


def false_alarm_by_method(name, labelled):
    """How often does each ratio method flag a *healthy* unit as faulted?

    This is the number the ratio-method literature almost never reports. A
    method that cannot output "healthy" is forced to alarm on every normal
    unit, which no amount of per-class recall will reveal.
    """
    normals = [s for s, t in labelled if t == "Normal"]
    rows = []
    for method in DEFAULT_METHODS:
        fired = 0
        for sample in normals:
            res = diagnose(sample, methods=(method,))
            code = res.results[0].code if res.results else "ND"
            if code not in NON_ALARM_CODES:
                fired += 1
        rows.append(OrderedDict([
            ("dataset", name),
            ("method", method),
            ("n_normal", len(normals)),
            ("flagged", fired),
            ("false_alarm_pct", round(100.0 * fired / len(normals), 1)
                if normals else None),
        ]))
    return rows


def binary_scores(pairs):
    """pairs: list of (is_fault_truth, alarm_fired)."""
    tp = sum(1 for t, a in pairs if t and a)
    fp = sum(1 for t, a in pairs if not t and a)
    tn = sum(1 for t, a in pairs if not t and not a)
    fn = sum(1 for t, a in pairs if t and not a)
    n = len(pairs)

    def rate(num, den):
        return round(100.0 * num / den, 1) if den else None

    return OrderedDict([
        ("n", n),
        ("tp", tp), ("fp", fp), ("tn", tn), ("fn", fn),
        ("accuracy_pct", rate(tp + tn, n)),
        ("recall_fault_pct", rate(tp, tp + fn)),      # sensitivity
        ("specificity_pct", rate(tn, tn + fp)),       # 1 - false alarm rate
        ("precision_pct", rate(tp, tp + fp)),
        ("false_alarm_pct", rate(fp, fp + tn)),
    ])


def evaluate_condition(name, labelled):
    """labelled: list of (GasSample, truth_label)."""
    rows = []
    by_label = Counter()
    condition_of_label = {}
    pairs = []
    per_sample = []

    normal_count = 0
    for sample, truth in labelled:
        if not truth:
            continue
        a = assess_condition(sample)
        is_fault = (truth != "Normal")
        if not is_fault:
            normal_count += 1
        alarm = a.condition >= ALARM_AT
        pairs.append((is_fault, alarm))
        by_label[(truth, a.condition)] += 1
        condition_of_label.setdefault(truth, []).append(a.condition)
        per_sample.append(OrderedDict([
            ("dataset", name),
            ("sample_id", sample.sample_id),
            ("truth", truth),
            ("is_fault", 1 if is_fault else 0),
            ("condition", a.condition),
            ("label", a.label),
            ("tdcg", round(a.tdcg, 3) if a.tdcg is not None else ""),
            ("tdcg_condition", a.tdcg_condition if a.tdcg_condition is not None else ""),
            ("limiting_gas", a.limiting_gas or ""),
            ("sampling_interval", a.sampling_interval),
            ("alarm", 1 if alarm else 0),
        ]))

    scores = binary_scores(pairs)
    scores["dataset"] = name
    scores["n_normal_labelled"] = normal_count

    # condition distribution overall, and mean condition per truth class
    dist = Counter()
    for (_truth, cond), n in by_label.items():
        dist[cond] += n

    mean_rows = []
    for truth in sorted(condition_of_label):
        vals = condition_of_label[truth]
        mean_rows.append(OrderedDict([
            ("dataset", name),
            ("truth", truth),
            ("n", len(vals)),
            ("mean_condition", round(sum(vals) / float(len(vals)), 3)),
            ("median_condition", sorted(vals)[len(vals) // 2]),
        ] + [("cond_" + str(c), sum(1 for v in vals if v == c)) for c in CONDITIONS]))

    return per_sample, scores, dist, mean_rows, by_label


def main():
    os.makedirs(OUT, exist_ok=True)
    all_scores = []
    all_mean = []
    all_by_label = []
    all_fa = []
    notes = []

    for name, loader in DATASETS.items():
        try:
            labelled = loader()
        except FileNotFoundError:
            print("skip {}: raw dataset not present in .cache/".format(name))
            continue
        labelled = [(s, t) for s, t in labelled if t]
        per_sample, scores, dist, mean_rows, by_label = evaluate_condition(name, labelled)
        if scores["n_normal_labelled"]:
            all_fa.extend(false_alarm_by_method(name, labelled))

        write_csv(os.path.join(OUT, "condition_per_sample_{}.csv".format(name)),
                  per_sample)
        all_scores.append(scores)
        all_mean.extend(mean_rows)
        for (truth, cond), n in sorted(by_label.items()):
            all_by_label.append(OrderedDict([
                ("dataset", name), ("truth", truth),
                ("condition", cond), ("n", n)]))
        notes.append((name, len(labelled), dist, scores))
        print("{}: {} samples, condition dist {}".format(
            name, len(labelled), dict(sorted(dist.items()))))

    if not all_scores:
        print("no datasets available - run scripts/fetch_datasets.py first")
        return

    write_csv(os.path.join(OUT, "condition_summary.csv"), all_scores)
    write_csv(os.path.join(OUT, "condition_by_label.csv"), all_mean)
    write_csv(os.path.join(OUT, "condition_crosstab.csv"), all_by_label)
    if all_fa:
        write_csv(os.path.join(OUT, "condition_false_alarm.csv"), all_fa)

    lines = []
    lines.append("# IEEE C57.104-2019 condition grading vs. published labels")
    lines.append("")
    lines.append("Generated by `experiments/run_condition.py`.")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append("The ratio methods ask *which* fault it is. Before that, an online")
    lines.append("monitor has to answer *whether anything is wrong*. IEEE C57.104-2019")
    lines.append("Table 1 grades every sample into Condition 1-4 from absolute")
    lines.append("concentrations and TDCG. This experiment scores that grading as a")
    lines.append("binary alarm (condition >= {}) against the datasets' own labels.".format(ALARM_AT))
    lines.append("")
    lines.append("## Alarm performance")
    lines.append("")
    header = ["dataset", "n", "normal labelled", "accuracy%", "recall(fault)%",
              "specificity%", "precision%", "false alarm%"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in all_scores:
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            s["dataset"], s["n"], s["n_normal_labelled"],
            _fmt(s["accuracy_pct"]), _fmt(s["recall_fault_pct"]),
            _fmt(s["specificity_pct"]), _fmt(s["precision_pct"]),
            _fmt(s["false_alarm_pct"])))
    lines.append("")
    lines.append("`specificity` is meaningful only where the dataset actually contains")
    lines.append("labelled healthy units; a dataset with no Normal class cannot produce")
    lines.append("false alarms by construction, so its specificity is undefined.")
    if all_fa:
        lines.append("")
        lines.append("## False alarm rate of the ratio methods on healthy units")
        lines.append("")
        lines.append("Scored only on samples labelled Normal. A method that cannot")
        lines.append("emit a \"healthy\" verdict is forced to alarm here, which is")
        lines.append("invisible in per-class recall.")
        lines.append("")
        lines.append("| dataset | method | normal units | flagged as fault | false alarm% |")
        lines.append("|---|---|---|---|---|")
        for r in all_fa:
            lines.append("| {} | {} | {} | {} | {} |".format(
                r["dataset"], r["method"], r["n_normal"], r["flagged"],
                _fmt(r["false_alarm_pct"])))
        lines.append("")
        lines.append("Duval Triangle has no normal zone at all, so it alarms on")
        lines.append("essentially every healthy unit. This is the concrete case for")
        lines.append("grading on absolute concentrations first: it decides *whether*")
        lines.append("to alarm far more reliably than any ratio method decides")
        lines.append("*which* fault it is.")

    lines.append("")
    lines.append("## Mean condition by true class")
    lines.append("")
    lines.append("| dataset | truth | n | mean condition | median | " +
                 " | ".join("C" + str(c) for c in CONDITIONS) + " |")
    lines.append("|" + "|".join(["---"] * (5 + len(CONDITIONS))) + "|")
    for r in all_mean:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            r["dataset"], r["truth"], r["n"], r["mean_condition"],
            r["median_condition"],
            " | ".join(str(r["cond_" + str(c)]) for c in CONDITIONS)))
    lines.append("")
    lines.append("## Condition distribution per dataset")
    lines.append("")
    for name, n, dist, _s in notes:
        total = sum(dist.values()) or 1
        parts = ", ".join("C{}={} ({:.1f}%)".format(c, dist.get(c, 0),
                                                    100.0 * dist.get(c, 0) / total)
                          for c in CONDITIONS)
        lines.append("- **{}** ({} samples): {}".format(name, n, parts))
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- Condition grading is threshold-based and knows nothing about gas ratios;")
    lines.append("  a high-reading but benign unit and an actively faulting one can")
    lines.append("  land in the same condition band.")
    lines.append("- TDCG can never raise the condition under Table 1: for every level k,")
    lines.append("  the sum of the per-gas Ck limits is below the Ck TDCG limit")
    lines.append("  (686 < 720, 1879 < 1920, 4585 < 4630). This is asserted by")
    lines.append("  `tests/test_condition.py::test_tdcg_never_raises_the_condition`.")
    lines.append("- Labels are the datasets' own annotations, not independent inspection.")

    with open(os.path.join(OUT, "CONDITION_REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print("")
    for s in all_scores:
        print("{:<14} n={:<5} acc={:>6}  recall(fault)={:>6}  spec={:>6}  FPR={:>6}".format(
            s["dataset"], s["n"], _fmt(s["accuracy_pct"]),
            _fmt(s["recall_fault_pct"]), _fmt(s["specificity_pct"]),
            _fmt(s["false_alarm_pct"])))
    print("")
    print("wrote {}".format(os.path.join(OUT, "CONDITION_REPORT.md")))


def _fmt(v):
    return "n/a" if v is None else "{:.1f}".format(v)


if __name__ == "__main__":
    main()
