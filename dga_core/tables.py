# -*- coding: utf-8 -*-
"""dga_core.tables

Static threshold / geometry tables for classical DGA interpretation methods.

PROVENANCE (all values transcribed from an MIT-licensed reference implementation):
    https://github.com/ToniMellin/dga-diagtool  (Copyright (c) 2022-2026 Toni Mellin)
    - IEC ratio method      -> diagnostic/diagnostic_calculation.py::iec_ratio_calculation
                               stated basis: IEC 60599 (2015)
    - Rogers ratio method   -> diagnostic/diagnostic_calculation.py::rogers_ratio_calculation
                               stated basis: IEEE C57.104-2019
    - Doernenburg method    -> diagnostic/diagnostic_calculation.py::doernenburg_ratio_calculation
                               stated basis: IEEE C57.104-2019
    - Duval Triangle 1 zones-> diagnostic/duval_triangle_1.py  (TRIANGLE1_*_A/B/C constants)

Ternary convention for Duval Triangle 1:
    A = CH4 (%), B = C2H2 (%), C = C2H4 (%), with A + B + C = 100.

NOTE: The classic IEC "three-ratio" 0/1/2 *coding* variant (GB/T 7252 style) is a
separate table and is NOT included here. It must be transcribed from the standard
text itself in Phase 1 and covered by unit tests before use.
"""

# ---------------------------------------------------------------------------
# Duval Triangle 1 zone polygons, as ternary (A=CH4, B=C2H2, C=C2H4) vertices
# ---------------------------------------------------------------------------

DUVAL1_ZONES = {
    "PD": [(100, 0, 0), (98, 2, 0), (98, 0, 2), (100, 0, 0)],
    "T1": [(96, 4, 0), (76, 4, 20), (80, 0, 20), (98, 0, 2), (98, 2, 0), (96, 4, 0)],
    "T2": [(80, 0, 20), (76, 4, 20), (46, 4, 50), (50, 0, 50), (80, 0, 20)],
    "T3": [(50, 0, 50), (35, 15, 50), (0, 15, 85), (0, 0, 100), (50, 0, 50)],
    "DT": [(87, 13, 0), (47, 13, 40), (31, 29, 40), (0, 29, 71),
           (0, 15, 85), (35, 15, 50), (46, 4, 50), (96, 4, 0), (87, 13, 0)],
    "D1": [(0, 100, 0), (0, 77, 23), (64, 13, 23), (87, 13, 0), (0, 100, 0)],
    "D2": [(64, 13, 23), (0, 77, 23), (0, 29, 71), (31, 29, 40),
           (47, 13, 40), (64, 13, 23)],
}

# Zone lookup order matters: DT overlaps D1/D2/T* boundaries in the reference
# implementation, so it is tested last.
DUVAL1_ZONE_ORDER = ("PD", "T1", "T2", "T3", "D1", "D2", "DT")

# ---------------------------------------------------------------------------
# Classic IEC three-ratio method (三比值法): coding table + fault lookup table
#
# PROVENANCE: two INDEPENDENT sources that agree entry-by-entry were used:
#   [S1] Lu & Chen, "Advanced Winding Models and Ontology-Based Fault Diagnosis",
#        University of Liverpool thesis (2014), Table 1.3 "IEC code for DGA fault
#        diagnosis"  -> https://livrepository.liverpool.ac.uk/19593/4/LuChe_July2014_19593.pdf
#   [S2] SSRG-IJEEE Vol.2 Issue 4 (2015), Table 2 "IEC codes" and Table 3
#        "Fault classifications according to the IEC gas ratio codes"
#        -> https://www.internationaljournalssrg.org/IJEEE/2015/Volume2-Issue4/IJEEE-V2I4P101.pdf
#
# Ratios (IEC 60599):
#   l = C2H2/C2H4   i = CH4/H2   k = C2H4/C2H6
#
# KNOWN DIVERGENCE IN THE LITERATURE (documented, not guessed):
#   * Some secondary sources swap D1/D2 for codes (1,0,1)/(1,0,2). We follow
#     [S1]+[S2], which agree, and which are also physically consistent:
#     a higher C2H4/C2H6 ratio means a higher-energy fault.
#   * Some sources generalise "discharge of low energy" to l in {1,2} and
#     k in {1,2}, which collides with the D2 entry at (1,0,2). Rather than
#     resolve the collision by guesswork, codes (2,0,1) and (2,0,2) return ND.
#   * An older Chinese variant (GB/T 7252 early editions) uses C2H2/C2H6 as the
#     third ratio instead of C2H4/C2H6. That variant is NOT implemented here.
# ---------------------------------------------------------------------------

# Range -> code, per ratio. Tuples are (upper_exclusive_bound, code);
# the last entry is the open-ended ">= bound" case.
IEC_CODE_RANGES = {
    # l = C2H2/C2H4
    "l": ((0.1, 0), (1.0, 1), (3.0, 1)),            # >= 3.0 -> 2
    # i = CH4/H2     NOTE the inverted first code
    "i": ((0.1, 1), (1.0, 0), (3.0, 2)),            # >= 3.0 -> 2
    # k = C2H4/C2H6
    "k": ((0.1, 0), (1.0, 0), (3.0, 1)),            # >= 3.0 -> 2
}
IEC_CODE_ABOVE_MAX = 2

# (l, i, k) -> (fault code, human-readable description)
IEC_FAULT_TABLE = {
    (0, 0, 0): ("Normal", "normal ageing"),
    (0, 1, 0): ("PD", "partial discharge of low energy density"),
    (1, 1, 0): ("PD", "partial discharge of high energy density / corona"),
    (1, 0, 1): ("D1", "discharge of low energy, continuous sparking"),
    (1, 0, 2): ("D2", "discharge of high energy, arcing"),
    (0, 0, 1): ("T1", "thermal fault < 150 C"),
    (0, 2, 0): ("T1", "thermal fault 150-300 C"),
    (0, 2, 1): ("T2", "thermal fault 300-700 C"),
    (0, 2, 2): ("T3", "thermal fault > 700 C"),
}

# ---------------------------------------------------------------------------
# Doernenburg pre-condition limits (ppm)
# ---------------------------------------------------------------------------

DOERNENBURG_LIMITS = {
    "h2_l1": 100.0,
    "ch4_l1": 120.0,
    "c2h2_l1": 1.0,
    "c2h4_l1": 50.0,
    "c2h6_l1": 65.0,
    "co_l1": 350.0,
}

# ---------------------------------------------------------------------------
# IEEE C57.104-2019 Table 1 - dissolved gas concentration limits by condition
# ---------------------------------------------------------------------------
# Condition 1: <= c1        Condition 2: c1 < v <= c2
# Condition 3: c2 < v <= c3 Condition 4: v > c3
#
# Provenance: two independent transcriptions of IEEE C57.104-2019 Table 1 agree
# digit-for-digit (a Krueger "Transformer Health Assessment" slide deck quoting
# the standard table, and a vendor DGA reference page). Where secondary sources
# disagreed (notably 90th-percentile "typical concentration" figures), the
# values below are NOT used - see docs/STANDARDS.md, Open items.
#
# NOTE: TDCG limits are specified independently by the standard and are NOT the
# column sum of the per-gas limits (C1 column sums to 686 ppm, not 720 ppm).
# Do not "correct" one against the other.
IEEE_C57_104_TABLE1 = {
    "H2":  (100.0, 700.0, 1800.0),
    "CH4": (120.0, 400.0, 1000.0),
    "C2H2": (1.0, 9.0, 35.0),
    "C2H4": (50.0, 100.0, 200.0),
    "C2H6": (65.0, 100.0, 150.0),
    "CO":  (350.0, 570.0, 1400.0),
    "CO2": (2500.0, 4000.0, 10000.0),
}

# Total dissolved combustible gas = H2 + CH4 + C2H6 + C2H4 + C2H2 + CO.
# CO2 is excluded from TDCG by definition (it is not combustible).
TDCG_GAS_KEYS = ("H2", "CH4", "C2H6", "C2H4", "C2H2", "CO")
IEEE_TDCG_LIMITS = (720.0, 1920.0, 4630.0)

# ---------------------------------------------------------------------------
# IEEE C57.104-2019 Table 3 - max absolute change between successive DGA
# samples (95th percentile), ppm. Index 0 = O2/N2 <= 0.2, index 1 = O2/N2 > 0.2
# ---------------------------------------------------------------------------
# IEEE_C57_104_ANY_INCREASE means the standard specifies "any increase" rather
# than a numeric bound: any positive delta on that gas is significant.
IEEE_C57_104_ANY_INCREASE = -1.0

IEEE_C57_104_TABLE3 = {
    "H2":  (40.0, 25.0),
    "CH4": (30.0, 10.0),
    "C2H6": (25.0, 7.0),
    "C2H4": (20.0, 20.0),
    "C2H2": (IEEE_C57_104_ANY_INCREASE, IEEE_C57_104_ANY_INCREASE),
    "CO":  (250.0, 175.0),
    "CO2": (2500.0, 1750.0),
}

# ---------------------------------------------------------------------------
# IEEE C57.104-2019 Table 4 - 95th percentile rate of gas increase, ppm/year,
# for a 3-6 point series whose gas levels are all below the Table 1 values.
# ---------------------------------------------------------------------------
# Shaped as: gas -> {"low_o2n2": (short_period, long_period),
#                    "high_o2n2": (short_period, long_period)}
# short period = 4-9 months between first and last point, long = 10-24 months.
IEEE_C57_104_TABLE4 = {
    "H2":  {"low_o2n2": (50.0, 20.0),  "high_o2n2": (25.0, 10.0)},
    "CH4": {"low_o2n2": (15.0, 10.0),  "high_o2n2": (4.0, 3.0)},
    "C2H6": {"low_o2n2": (15.0, 9.0),  "high_o2n2": (3.0, 2.0)},
    "C2H4": {"low_o2n2": (10.0, 7.0),  "high_o2n2": (7.0, 5.0)},
    "C2H2": {"low_o2n2": (IEEE_C57_104_ANY_INCREASE, IEEE_C57_104_ANY_INCREASE),
             "high_o2n2": (IEEE_C57_104_ANY_INCREASE, IEEE_C57_104_ANY_INCREASE)},
    "CO":  {"low_o2n2": (200.0, 100.0), "high_o2n2": (100.0, 80.0)},
    "CO2": {"low_o2n2": (2500.0, 1500.0), "high_o2n2": (1750.0, 1000.0)},
}

# Recommended sampling interval by condition (IEEE C57.104-2019 Table 5).
# Provenance: single secondary source; treated as guidance, not a hard rule.
SAMPLING_INTERVAL_BY_CONDITION = {
    1: "annual",
    2: "monthly",
    3: "weekly",
    4: "daily / continuous",
}

CONDITION_LABELS = {
    1: "Normal",
    2: "Investigate",
    3: "Warning",
    4: "Critical",
}

# ---------------------------------------------------------------------------
# Result sentinel codes
# ---------------------------------------------------------------------------

NA = "N/A"      # required input missing
ND = "ND"       # ratios computable but no fault zone matched
ERR = "-"
