# -*- coding: utf-8 -*-
"""dga_core.methods

Classical DGA interpretation methods, implemented with the standard library only
(math). No numpy, no pandas, no matplotlib - this is what makes the module
deployable on a Jetson Nano running Python 3.6.

Methods
    iec_ratio       IEC 60599 (2015) ratio method
    rogers_ratio    Rogers ratio method, IEEE C57.104-2019
    doernenburg     Doernenburg ratio method, IEEE C57.104-2019
    duval_triangle1 Duval Triangle 1 (7 zones)

Ratio numbering follows IEEE C57.104:
    r1 = CH4/H2    r2 = C2H2/C2H4    r3 = C2H2/CH4    r4 = C2H6/C2H2    r5 = C2H4/C2H6
"""

from math import sqrt

from .exceptions import InsufficientGasData
from .models import GasSample, GasRatios, MethodResult, DiagnosisResult
from .tables import (
    DUVAL1_ZONES, DUVAL1_ZONE_ORDER, DOERNENBURG_LIMITS,
    IEC_CODE_RANGES, IEC_CODE_ABOVE_MAX, IEC_FAULT_TABLE,
    NA, ND,
)


# ---------------------------------------------------------------------------
# ratio computation
# ---------------------------------------------------------------------------

def _div(num, den):
    """Safe division. Any degenerate input yields None rather than raising,
    so that a single unusable ratio never aborts the whole diagnosis."""
    if num is None or den is None:
        return None
    if den == 0:
        return None
    try:
        v = num / den
    except (TypeError, ZeroDivisionError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def compute_ratios(sample):
    # type: (GasSample) -> GasRatios
    """Compute all five classical ratios from a sample."""
    return GasRatios(
        r1=_div(sample.ch4, sample.h2),
        r2=_div(sample.c2h2, sample.c2h4),
        r3=_div(sample.c2h2, sample.ch4),
        r4=_div(sample.c2h6, sample.c2h2),
        r5=_div(sample.c2h4, sample.c2h6),
    )


# ---------------------------------------------------------------------------
# IEC 60599 (2015) ratio method
# ---------------------------------------------------------------------------

def iec_ratio(sample, ratios=None):
    # type: (GasSample, GasRatios) -> MethodResult
    """IEC 60599 (2015) interpretation using r1 (CH4/H2), r2 (C2H2/C2H4),
    r5 (C2H4/C2H6)."""
    r = ratios or compute_ratios(sample)
    if r.r2 is None or r.r1 is None or r.r5 is None:
        return MethodResult("iec_ratio", NA, False,
                            "one or more of C2H2/C2H4, CH4/H2, C2H4/C2H6 is undefined")

    if r.r1 < 0.1 and r.r5 < 0.2:
        return MethodResult("iec_ratio", "PD", True)
    if r.r2 > 1 and 0.1 <= r.r1 <= 0.5 and r.r5 > 1:
        return MethodResult("iec_ratio", "D1", True)
    if 0.6 <= r.r2 <= 2.5 and 0.1 <= r.r1 <= 1 and r.r5 > 2:
        return MethodResult("iec_ratio", "D2", True)
    if r.r1 > 1 and r.r5 < 1:
        return MethodResult("iec_ratio", "T1", True)
    if r.r2 < 0.1 and r.r1 > 1 and 1 <= r.r5 <= 4:
        return MethodResult("iec_ratio", "T2", True)
    if r.r2 < 0.2 and r.r1 > 1 and r.r5 > 4:
        return MethodResult("iec_ratio", "T3", True)
    return MethodResult("iec_ratio", ND, False, "no IEC 60599 zone matched")


def _iec_code(value, ranges):
    """Map a ratio value onto its 0/1/2 code."""
    for upper, code in ranges:
        if value < upper:
            return code
    return IEC_CODE_ABOVE_MAX


def iec_three_ratio(sample, ratios=None):
    # type: (GasSample, GasRatios) -> MethodResult
    """Classic IEC three-ratio method (三比值法).

    Encodes l = C2H2/C2H4, i = CH4/H2, k = C2H4/C2H6 into 0/1/2 and looks the
    triple up in IEC_FAULT_TABLE. This is the coded variant, distinct from
    :func:`iec_ratio` (the direct-ratio-band variant from IEC 60599:2015).
    """
    r = ratios or compute_ratios(sample)
    if r.r2 is None or r.r1 is None or r.r5 is None:
        return MethodResult("iec_three_ratio", NA, False,
                            "one or more of C2H2/C2H4, CH4/H2, C2H4/C2H6 is undefined")

    l = _iec_code(r.r2, IEC_CODE_RANGES["l"])
    i = _iec_code(r.r1, IEC_CODE_RANGES["i"])
    k = _iec_code(r.r5, IEC_CODE_RANGES["k"])

    entry = IEC_FAULT_TABLE.get((l, i, k))
    if entry is None:
        return MethodResult(
            "iec_three_ratio", ND, False,
            "code triple ({},{},{}) is not covered by the IEC fault table".format(l, i, k))
    code, desc = entry
    return MethodResult("iec_three_ratio", code, True, desc)


# ---------------------------------------------------------------------------
# Rogers ratio method (IEEE C57.104-2019)
# ---------------------------------------------------------------------------

def rogers_ratio(sample, ratios=None):
    # type: (GasSample, GasRatios) -> MethodResult
    """Rogers ratio method using r1, r2, r5."""
    r = ratios or compute_ratios(sample)
    if r.r2 is None or r.r1 is None or r.r5 is None:
        return MethodResult("rogers_ratio", NA, False,
                            "one or more of C2H2/C2H4, CH4/H2, C2H4/C2H6 is undefined")

    if r.r2 < 0.1 and 0.1 <= r.r1 <= 1 and r.r5 < 1:
        return MethodResult("rogers_ratio", "Normal", True)
    if r.r2 < 0.1 and r.r1 < 0.1 and r.r5 < 1:
        return MethodResult("rogers_ratio", "PD", True)
    if 0.1 <= r.r2 <= 3 and 0.1 <= r.r1 <= 1 and r.r5 > 3:
        return MethodResult("rogers_ratio", "D2", True)
    if r.r2 < 0.1 and 0.1 <= r.r1 <= 1 and 1 <= r.r5 <= 3:
        return MethodResult("rogers_ratio", "T1", True)
    if r.r2 < 0.1 and r.r1 > 1 and 1 <= r.r5 <= 3:
        return MethodResult("rogers_ratio", "T2", True)
    if r.r2 < 0.1 and r.r1 > 1 and r.r5 > 3:
        return MethodResult("rogers_ratio", "T3", True)
    return MethodResult("rogers_ratio", ND, False, "no Rogers zone matched")


# ---------------------------------------------------------------------------
# Doernenburg ratio method (IEEE C57.104-2019)
# ---------------------------------------------------------------------------

def doernenburg(sample, ratios=None):
    # type: (GasSample, GasRatios) -> MethodResult
    """Doernenburg ratio method. Requires CO to evaluate the pre-conditions."""
    r = ratios or compute_ratios(sample)
    if r.r1 is None or r.r2 is None or r.r3 is None or r.r4 is None:
        return MethodResult("doernenburg", NA, False, "required ratio undefined")

    L = DOERNENBURG_LIMITS
    if sample.co is None:
        return MethodResult("doernenburg", NA, False, "CO is required by Doernenburg")

    exceeding = (sample.h2 > 2 * L["h2_l1"]
                 or sample.ch4 > 2 * L["ch4_l1"]
                 or sample.c2h2 > 2 * L["c2h2_l1"]
                 or sample.c2h4 > 2 * L["c2h4_l1"])
    if not (exceeding and (sample.c2h6 > L["c2h6_l1"] or sample.co > L["co_l1"])):
        return MethodResult("doernenburg", "No fault", True,
                            "Doernenburg pre-conditions not met")

    applicable = ((sample.ch4 > L["ch4_l1"] or sample.h2 > L["h2_l1"])
                  and (sample.c2h2 > L["c2h2_l1"] or sample.c2h4 > L["c2h4_l1"])
                  and (sample.c2h2 > L["c2h2_l1"] or sample.ch4 > L["ch4_l1"])
                  and (sample.c2h6 > L["c2h6_l1"] or sample.c2h2 > L["c2h2_l1"]))
    if not applicable:
        return MethodResult("doernenburg", NA, False,
                            "gas levels below Doernenburg applicability limits")

    if r.r1 > 1 and r.r2 < 0.75 and r.r3 < 0.3 and r.r4 > 0.4:
        return MethodResult("doernenburg", "T", True)
    if r.r1 < 0.1 and r.r3 < 0.3 and r.r4 > 0.4:
        return MethodResult("doernenburg", "PD", True)
    if 0.1 < r.r1 < 1 and r.r2 > 0.75 and r.r3 > 0.3 and r.r4 < 0.4:
        return MethodResult("doernenburg", "D1/D2", True)
    return MethodResult("doernenburg", ND, False, "no Doernenburg zone matched")


# ---------------------------------------------------------------------------
# Duval Triangle 1
# ---------------------------------------------------------------------------

_SQRT3_2 = sqrt(3.0) / 2.0


def _ternary_to_cartesian(a, b, c):
    """Map a ternary triple (A=CH4, B=C2H2, C=C2H4) to 2-D Cartesian.

    Vertices: A -> (0, 0), C -> (1, 0), B -> (0.5, sqrt(3)/2).
    """
    total = a + b + c
    if total == 0:
        raise InsufficientGasData("Duval triangle requires CH4 + C2H2 + C2H4 > 0")
    x = 0.5 * (2.0 * c + b) / total
    y = _SQRT3_2 * b / total
    return x, y


_VERTEX_EPS = 1e-9


def _point_in_polygon(x, y, poly):
    """Ray-casting point-in-polygon test.

    A vertex-proximity short-circuit is applied first. This matters for real
    data: a sample with C2H2 = 0 and C2H4 = 0 normalises to exactly the CH4
    apex, and a strict ray-cast classifies an exact vertex as outside. The
    half-open comparison below is otherwise correct but deliberately excludes
    points lying precisely on a vertex.
    """
    for xi, yi in poly:
        if abs(x - xi) <= _VERTEX_EPS and abs(y - yi) <= _VERTEX_EPS:
            return True

    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _zone_polygon_cartesian(zone):
    return [_ternary_to_cartesian(a, b, c) for (a, b, c) in DUVAL1_ZONES[zone]]


# Precompute polygons once at import: this is the only "model" the method needs,
# and it is a few dozen floats.
_ZONE_POLYGONS = dict((z, _zone_polygon_cartesian(z)) for z in DUVAL1_ZONE_ORDER)


def duval_triangle1(sample):
    # type: (GasSample) -> MethodResult
    """Duval Triangle 1 zone classification."""
    if sample.ch4 is None or sample.c2h2 is None or sample.c2h4 is None:
        return MethodResult("duval_triangle1", NA, False, "CH4, C2H2, C2H4 required")

    total = sample.ch4 + sample.c2h2 + sample.c2h4
    if total <= 0:
        return MethodResult("duval_triangle1", NA, False,
                            "CH4 + C2H2 + C2H4 = 0, triangle undefined")

    try:
        x, y = _ternary_to_cartesian(sample.ch4, sample.c2h2, sample.c2h4)
    except InsufficientGasData:
        return MethodResult("duval_triangle1", NA, False, "triangle degenerate")

    for zone in DUVAL1_ZONE_ORDER:
        if _point_in_polygon(x, y, _ZONE_POLYGONS[zone]):
            return MethodResult("duval_triangle1", zone, True)

    return MethodResult("duval_triangle1", ND, False,
                        "point falls outside all Duval Triangle 1 zones")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

METHOD_REGISTRY = {
    "iec_three_ratio": iec_three_ratio,
    "iec_ratio": iec_ratio,
    "rogers_ratio": rogers_ratio,
    "doernenburg": doernenburg,
    "duval_triangle1": duval_triangle1,
}

# Methods that run by default: Doernenburg is excluded because it needs CO,
# which most public DGA datasets do not carry.
DEFAULT_METHODS = ("iec_three_ratio", "iec_ratio", "rogers_ratio", "duval_triangle1")


def diagnose(sample, methods=None, validate_input=True):
    """Run the requested methods against one sample.

    :param methods: iterable of method names; defaults to all except
                    Doernenburg (which needs CO and is often unavailable).
    """
    if validate_input:
        from .validation import validate
        validate(sample)

    if methods is None:
        methods = DEFAULT_METHODS

    ratios = compute_ratios(sample)
    results = []
    for name in methods:
        fn = METHOD_REGISTRY[name]
        if name == "duval_triangle1":
            results.append(fn(sample))
        else:
            results.append(fn(sample, ratios))
    return DiagnosisResult(sample.sample_id, tuple(results), ratios)
