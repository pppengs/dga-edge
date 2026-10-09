# -*- coding: utf-8 -*-
"""experiments.loaders

HOST-SIDE ONLY. Converts the raw public datasets into GasSample lists.

openpyxl is imported lazily inside the functions so that importing this module
never drags a third-party package into an embedded environment. This module is
explicitly excluded from the deployment manifest.
"""

import os

from dga_core import GasSample

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")

# Unified label mapping onto IEC 60599 fault codes. The two source datasets use
# different vocabularies; anything that cannot be mapped is returned as None so
# the caller can exclude it rather than mislabel it.
LABEL_MAP = {
    "局部放电": "PD",
    "低能放电": "D1",
    "高能放电": "D2",
    "低温过热": "T1",
    "中温过热": "T2",
    "高温过热": "T3",
    "中低温过热": "T1",   # Cliango merges 150-300C and 300-700C; mapped to the lower tier
    "正常": "Normal",
}

GAS_COLUMNS = ["H2", "CH4", "C2H6", "C2H4", "C2H2"]


def _read_sheet(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.values)
    wb.close()
    return rows


def load_alan456(path=None):
    """589 samples, 6 classes (no Normal class)."""
    path = path or os.path.join(CACHE, "a589.xlsx")
    rows = _read_sheet(path)
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}
    out = []
    for n, r in enumerate(rows[1:]):
        if r[idx["H2"]] is None:
            continue
        label_raw = str(r[idx["故障类型"]]).strip()
        out.append((
            GasSample(h2=float(r[idx["H2"]]), ch4=float(r[idx["CH4"]]),
                      c2h6=float(r[idx["C2H6"]]), c2h4=float(r[idx["C2H4"]]),
                      c2h2=float(r[idx["C2H2"]]), sample_id="a589-{:04d}".format(n)),
            LABEL_MAP.get(label_raw),
        ))
    return out


def load_cliango(path=None):
    """202 samples, 6 classes, includes a Normal class.

    The published sheet carries a duplicated header row, so row 0 is skipped
    twice (header=1 in pandas terms).
    """
    path = path or os.path.join(CACHE, "cliango.xlsx")
    rows = _read_sheet(path)
    header = [str(c).strip() if c else "" for c in rows[1]]
    idx = {name: i for i, name in enumerate(header)}
    h2 = next(k for k in idx if k.startswith("氢气"))
    ch4 = next(k for k in idx if k.startswith("甲烷"))
    c2h6 = next(k for k in idx if k.startswith("乙烷"))
    c2h4 = next(k for k in idx if k.startswith("乙烯"))
    c2h2 = next(k for k in idx if k.startswith("乙炔"))
    fault = next(k for k in idx if k.startswith("故障"))
    out = []
    for n, r in enumerate(rows[2:]):
        if r[idx[h2]] is None:
            continue
        label_raw = str(r[idx[fault]]).strip()
        out.append((
            GasSample(h2=float(r[idx[h2]]), ch4=float(r[idx[ch4]]),
                      c2h6=float(r[idx[c2h6]]), c2h4=float(r[idx[c2h4]]),
                      c2h2=float(r[idx[c2h2]]), sample_id="cliango-{:04d}".format(n)),
            LABEL_MAP.get(label_raw),
        ))
    return out


DATASETS = {
    "alan456_589": load_alan456,
    "cliango_202": load_cliango,
}
