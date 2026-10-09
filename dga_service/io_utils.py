# -*- coding: utf-8 -*-
"""dga_service.io_utils

CSV / JSONL input and output for the batch pipeline.

Standard library only (csv, json) - this module is safe to ship to the
embedded target. Excel reading deliberately lives in experiments/loaders.py
and is a host-side-only concern, because openpyxl must never become a
dependency of anything deployed to the board.
"""

import csv
import json
import os

from dga_core import GasSample
from dga_core.exceptions import DGAError
from dga_core.validation import flag_sentinel_zeros

# Accepted column aliases -> canonical gas name. Real-world exports are messy;
# this table is what keeps the CLI usable against arbitrary utility CSVs.
COLUMN_ALIASES = {
    "h2": "h2", "hydrogen": "h2", "hydrogen_h2": "h2", "氢气": "h2", "氢气h2": "h2",
    "ch4": "ch4", "methane": "ch4", "甲烷": "ch4", "甲烷ch4": "ch4",
    "c2h6": "c2h6", "ethane": "c2h6", "乙烷": "c2h6", "乙烷c2h6": "c2h6",
    "c2h4": "c2h4", "ethylene": "c2h4", "乙烯": "c2h4", "乙烯c2h4": "c2h4",
    "c2h2": "c2h2", "acetylene": "c2h2", "乙炔": "c2h2", "乙炔c2h2": "c2h2",
    "co": "co", "carbonmonoxide": "co", "一氧化碳": "co",
    "co2": "co2", "carbondioxide": "co2", "二氧化碳": "co2",
}

# NOTE: keys are normalised by _norm() first, which strips spaces and
# underscores - so "unit_id" arrives here as "unitid". Compound aliases must be
# written in that collapsed form.
ID_ALIASES = ("id", "sampleid", "sample", "group", "name", "unit", "tag",
              "unitid", "transformerid", "deviceid", "assetid", "serial",
              "transformer", "asset", "device",
              "编号", "组号", "组别", "设备", "样本", "变压器", "装置")

DATE_ALIASES = ("date", "time", "timestamp", "datetime", "sampledate",
                "采样日期", "日期", "时间")

GAS_FIELDS = ("h2", "ch4", "c2h6", "c2h4", "c2h2", "co", "co2")

# Accepted timestamp layouts. Kept to strptime so this stays stdlib-only and
# parses on Python 3.6.
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d",
                "%d/%m/%Y", "%Y.%m.%d")


def _norm(name):
    if name is None:
        return ""
    return str(name).strip().lower().replace(" ", "").replace("_", "")


def _map_columns(header):
    """Return (gas_mapping, id_col, date_col) for the recognised columns."""
    mapping = {}
    id_col = None
    date_col = None
    for i, raw in enumerate(header):
        key = _norm(raw)
        if key in COLUMN_ALIASES:
            mapping[COLUMN_ALIASES[key]] = i
        elif key in ID_ALIASES and id_col is None:
            id_col = i
        elif key in DATE_ALIASES and date_col is None:
            date_col = i
    return mapping, id_col, date_col


def parse_date(text):
    """Parse a sampling timestamp. Returns None when it cannot be parsed.

    Uses only datetime.strptime - no dateutil, so this ships to the board.
    """
    from datetime import datetime
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    text = str(value).strip()
    if text == "" or text.lower() in ("na", "n/a", "nan", "null", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        raise DGAError("cannot parse '{}' as a concentration".format(value))


def read_csv(path, strict=False):
    """Read a DGA CSV into a list of (GasSample, raw_row) tuples.

    Rows that cannot be parsed are reported rather than silently dropped:
    the second element of each tuple carries the original row so the caller
    can audit what happened.
    """
    samples = []
    errors = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return [], ["empty file"]

        mapping, id_col, date_col = _map_columns(header)
        if not mapping:
            raise DGAError("no recognised gas columns in header: {}".format(header))

        for lineno, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue
            try:
                values = {}
                for field in GAS_FIELDS:
                    idx = mapping.get(field)
                    values[field] = _to_float(row[idx]) if idx is not None and idx < len(row) else None
                sid = row[id_col].strip() if id_col is not None and id_col < len(row) else str(lineno - 1)
                stamp = parse_date(row[date_col]) if date_col is not None and date_col < len(row) else None
                samples.append((GasSample(sample_id=sid, **values), row, stamp))
            except DGAError as exc:
                if strict:
                    raise
                errors.append("line {}: {}".format(lineno, exc))
    return samples, errors


def read_csv_series(path):
    """Read a DGA CSV as a time series grouped by unit id.

    :returns: (OrderedDict of sample_id -> [(datetime, GasSample), ...] sorted
               ascending by time, errors). Rows without a parseable timestamp
               are reported as errors and excluded, because a rate of change
               cannot be computed without an interval.
    """
    try:
        from collections import OrderedDict
    except ImportError:  # pragma: no cover - py3.6 always has it
        OrderedDict = dict

    samples, errors = read_csv(path)
    series = OrderedDict()
    for sample, _row, stamp in samples:
        if stamp is None:
            errors.append("{}: no parseable date, excluded from the trend".format(
                sample.sample_id))
            continue
        series.setdefault(sample.sample_id, []).append((stamp, sample))
    for sid in series:
        series[sid].sort(key=lambda pair: pair[0])
    return series, errors


def _condition_columns(status):
    """Flatten a MonitorStatus into CSV-ready string columns."""
    if status is None:
        return {}
    a = status.assessment
    row = {
        "condition": status.condition,
        "condition_label": status.label,
        "tdcg": "" if a.tdcg is None else "{:.4g}".format(a.tdcg),
        "tdcg_condition": "" if a.tdcg_condition is None else a.tdcg_condition,
        "limiting_gas": a.limiting_gas or "",
        "sampling_interval": a.sampling_interval,
        "rate_escalated": "1" if status.rate_escalated else "0",
    }
    if status.rate is not None:
        row["rate_significant"] = "1" if status.rate.significant else "0"
        row["rate_gases_t3"] = ",".join(status.rate.exceeding_table3)
        row["rate_gases_t4"] = ",".join(status.rate.exceeding_table4)
        row["interval_days"] = "{:.4g}".format(status.rate.days)
    return row


def results_to_rows(results, conditions=None):
    """Flatten DiagnosisResult objects into CSV-ready dict rows.

    :param conditions: optional list/dict of MonitorStatus aligned with
                       ``results`` (list order, or keyed by sample_id).
    """
    rows = []
    for i, res in enumerate(results):
        row = {"sample_id": res.sample_id}
        for key, value in res.ratios._asdict().items():
            row["ratio_" + key] = "" if value is None else "{:.6g}".format(value)
        for m in res.results:
            row[m.method] = m.code
            row[m.method + "_ok"] = "1" if m.applicable else "0"
        if conditions:
            status = conditions[i] if isinstance(conditions, (list, tuple)) else conditions.get(res.sample_id)
            row.update(_condition_columns(status))
        rows.append(row)
    return rows


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path, results, conditions=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for i, res in enumerate(results):
            payload = {
                "sample_id": res.sample_id,
                "ratios": {k: v for k, v in res.ratios._asdict().items()},
                "results": [
                    {"method": m.method, "code": m.code,
                     "applicable": m.applicable, "reason": m.reason}
                    for m in res.results
                ],
            }
            if conditions:
                status = (conditions[i] if isinstance(conditions, (list, tuple))
                          else conditions.get(res.sample_id))
                if status is not None:
                    payload["condition"] = status.as_dict()
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def sentinel_report(samples):
    """Count how many samples carry sub-detection-limit sentinel values."""
    n = 0
    detail = {}
    for sample, _row, _stamp in samples:
        flagged = flag_sentinel_zeros(sample)
        if flagged:
            n += 1
            for gas in flagged:
                detail[gas] = detail.get(gas, 0) + 1
    return n, detail
