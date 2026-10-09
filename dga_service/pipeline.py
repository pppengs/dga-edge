# -*- coding: utf-8 -*-
"""dga_service.pipeline

Batch diagnosis orchestration: validation, per-sample error isolation, and
aggregate reporting. Nothing here is allowed to let one bad row abort a run.
"""

from collections import Counter, OrderedDict

from dga_core import diagnose, monitor, DEFAULT_METHODS
from dga_core.condition import CONDITION_LABELS
from dga_core.exceptions import DGAError
from dga_core.models import GasSample

from .io_utils import sentinel_report


class BatchReport(object):
    """Result of a batch run: per-sample outcomes plus aggregate counters."""

    def __init__(self, methods):
        self.methods = list(methods)
        self.results = []
        self.failures = []          # (sample_id, error message)
        self.skipped_invalid = 0
        # MonitorStatus per sample, keyed by sample_id and kept in result order
        # so it can be zipped with self.results for CSV/JSONL export.
        self.conditions = []

    # -- aggregation ----------------------------------------------------
    def code_counts(self):
        out = {}
        for name in self.methods:
            c = Counter(m.code for res in self.results for m in res.results
                        if m.method == name)
            out[name] = c
        return out

    def decision_rates(self):
        """Fraction of samples each method could actually decide on."""
        total = len(self.results)
        out = OrderedDict()
        for name in self.methods:
            decided = sum(1 for r in self.results
                          for m in r.results if m.method == name and m.applicable)
            out[name] = (decided, total, (100.0 * decided / total) if total else 0.0)
        return out

    def agreement(self, a, b):
        """How often two methods agree, restricted to samples both decided on."""
        both = 0
        same = 0
        for r in self.results:
            codes = dict((m.method, m) for m in r.results)
            ma, mb = codes.get(a), codes.get(b)
            if ma is None or mb is None:
                continue
            if not (ma.applicable and mb.applicable):
                continue
            both += 1
            if ma.code == mb.code:
                same += 1
        return same, both, (100.0 * same / both) if both else 0.0

    def condition_counts(self):
        """Counter of IEEE C57.104 condition levels across the batch."""
        return Counter(c.condition for c in self.conditions)

    def escalated_count(self):
        """How many samples had their condition raised by the rate of change."""
        return sum(1 for c in self.conditions if c.rate_escalated)

    def conditions_by_id(self):
        return dict((c.sample_id, c) for c in self.conditions)

    def summary_lines(self):
        lines = []
        lines.append("samples processed : {}".format(len(self.results)))
        lines.append("validation failures: {}".format(len(self.failures)))
        rates = self.decision_rates()
        lines.append("")
        lines.append("{:<18} {:>10} {:>10}".format("method", "decided", "rate"))
        for name, (decided, total, pct) in rates.items():
            lines.append("{:<18} {:>5}/{:<5} {:>9.1f}%".format(name, decided, total, pct))
        lines.append("")
        for name, counts in self.code_counts().items():
            parts = "  ".join("{}={}".format(k, v) for k, v in counts.most_common())
            lines.append("{:<18} {}".format(name, parts))

        if self.conditions:
            counts = self.condition_counts()
            lines.append("")
            lines.append("IEEE C57.104 condition ({} samples):".format(len(self.conditions)))
            for level in sorted(counts):
                n = counts[level]
                lines.append("  Condition {} {:>12} {:>5} ({:5.1f}%)".format(
                    level, CONDITION_LABELS[level], n,
                    100.0 * n / len(self.conditions)))
            esc = self.escalated_count()
            if esc:
                lines.append("  rate-escalated : {}".format(esc))
        return "\n".join(lines)


def _unwrap(item):
    """Accept a bare GasSample or a (sample, ...) tuple.

    NOTE: GasSample is a NamedTuple, so `isinstance(item, tuple)` is True for
    bare samples too. Test for the sample type explicitly.
    """
    if isinstance(item, GasSample):
        return item
    return item[0]


def run_batch(samples, methods=None, validate_input=True, with_condition=True):
    """Diagnose every sample, and optionally assess its condition.

    :param samples: iterable of GasSample, or of (GasSample, raw_row, stamp)
                    tuples as produced by io_utils.read_csv
    :param with_condition: also run the IEEE C57.104-2019 Table 1 assessment
    :returns: BatchReport
    """
    methods = tuple(methods or DEFAULT_METHODS)
    report = BatchReport(methods)

    for item in samples:
        sample = _unwrap(item)
        try:
            result = diagnose(sample, methods=methods, validate_input=validate_input)
            report.results.append(result)
        except DGAError as exc:
            report.failures.append((sample.sample_id, str(exc)))
            continue
        except Exception as exc:  # never let one row kill the batch
            report.failures.append((sample.sample_id, "unexpected: {}".format(exc)))
            continue

        if with_condition:
            try:
                report.conditions.append(monitor(sample))
            except Exception as exc:  # condition monitoring must not break diagnosis
                report.failures.append((sample.sample_id,
                                        "condition: {}".format(exc)))

    return report


def run_trend(series, o2n2_ratio=None):
    """Condition monitoring over a time series, one entry per unit.

    :param series: {sample_id: [(datetime, GasSample), ...]} sorted ascending
    :param o2n2_ratio: O2/N2 ratio, selects the IEEE C57.104 table column
    :returns: list of MonitorStatus, one per unit, for its latest sample
    """
    out = []
    for sid, points in series.items():
        if not points:
            continue
        stamp, current = points[-1]
        previous = points[-2][1] if len(points) >= 2 else None
        if previous is None:
            out.append(monitor(current))
            continue
        days = (stamp - points[-2][0]).total_seconds() / 86400.0
        if days <= 0:
            # Duplicate or out-of-order timestamps: report the absolute
            # assessment rather than inventing an interval.
            out.append(monitor(current))
            continue
        out.append(monitor(current, previous=previous, days=days,
                           o2n2_ratio=o2n2_ratio))
    return out


def sentinel_summary(samples):
    return sentinel_report(samples) if samples and not isinstance(samples[0], GasSample) else (0, {})
