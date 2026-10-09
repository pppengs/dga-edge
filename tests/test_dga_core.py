# -*- coding: utf-8 -*-
"""Unit tests for dga_core.

Runs with the standard library only:
    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dga_core import (  # noqa: E402
    GasSample, diagnose, compute_ratios,
    iec_three_ratio, iec_ratio, rogers_ratio, doernenburg, duval_triangle1,
    validate, flag_sentinel_zeros, METHOD_REGISTRY,
)
from dga_core.exceptions import (  # noqa: E402
    DGAValidationError, MissingGasError,
)
from dga_core.tables import IEC_FAULT_TABLE  # noqa: E402


def S(h2=100.0, ch4=50.0, c2h6=50.0, c2h4=100.0, c2h2=10.0, co=None, co2=None, sid="t"):
    return GasSample(h2=h2, ch4=ch4, c2h6=c2h6, c2h4=c2h4, c2h2=c2h2, co=co, co2=co2, sample_id=sid)


class TestRatios(unittest.TestCase):
    def test_basic(self):
        r = compute_ratios(S(h2=100.0, ch4=50.0, c2h6=50.0, c2h4=200.0, c2h2=20.0))
        self.assertAlmostEqual(r.r1, 0.5)
        self.assertAlmostEqual(r.r2, 0.1)
        self.assertAlmostEqual(r.r3, 0.4)
        self.assertAlmostEqual(r.r4, 2.5)
        self.assertAlmostEqual(r.r5, 4.0)

    def test_zero_denominator_is_none_not_exception(self):
        r = compute_ratios(S(h2=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0))
        self.assertIsNone(r.r1)
        self.assertIsNone(r.r5)

    def test_missing_gas_is_none(self):
        s = GasSample(h2=10.0, ch4=None, c2h6=1.0, c2h4=2.0, c2h2=0.0)
        r = compute_ratios(s)
        self.assertIsNone(r.r3)
        self.assertIsNone(r.r1)


class TestIECCoding(unittest.TestCase):
    """Coding boundaries per IEC_CODE_RANGES (sources documented in tables.py)."""

    def test_code_l(self):
        # l = C2H2/C2H4 : <0.1 -> 0 ; [0.1,3) -> 1 ; >=3 -> 2
        cases = [(0.05, 0), (0.0999, 0), (0.1, 1), (0.5, 1), (2.999, 1), (3.0, 2), (10.0, 2)]
        for value, expected in cases:
            s = S(h2=100.0, ch4=50.0, c2h6=50.0, c2h4=100.0, c2h2=100.0 * value)
            self.assertEqual(_triple(s)[0], expected, "l={}".format(value))

    def test_code_i(self):
        # i = CH4/H2 : <0.1 -> 1 ; [0.1,1) -> 0 ; >=1 -> 2
        cases = [(0.05, 1), (0.1, 0), (0.5, 0), (0.999, 0), (1.0, 2), (5.0, 2)]
        for value, expected in cases:
            s = S(h2=100.0, ch4=100.0 * value, c2h6=50.0, c2h4=100.0, c2h2=10.0)
            self.assertEqual(_triple(s)[1], expected, "i={}".format(value))

    def test_code_k(self):
        # k = C2H4/C2H6 : <1 -> 0 ; [1,3) -> 1 ; >=3 -> 2
        cases = [(0.05, 0), (0.5, 0), (0.999, 0), (1.0, 1), (2.5, 1), (3.0, 2), (9.0, 2)]
        for value, expected in cases:
            s = S(h2=100.0, ch4=50.0, c2h6=100.0, c2h4=100.0 * value, c2h2=10.0)
            self.assertEqual(_triple(s)[2], expected, "k={}".format(value))


# helpers used by the coding tests above
from dga_core.methods import _iec_code      # noqa: E402
from dga_core.tables import IEC_CODE_RANGES  # noqa: E402


def _code_of(s):
    r = compute_ratios(s)
    return (_iec_code(r.r2, IEC_CODE_RANGES["l"]),
            _iec_code(r.r1, IEC_CODE_RANGES["i"]),
            _iec_code(r.r5, IEC_CODE_RANGES["k"]))


def _triple(s):
    return _code_of(s)


class TestIECFaultTable(unittest.TestCase):
    """One crafted sample per canonical (l, i, k) entry."""

    CASES = [
        # (H2, CH4, C2H6, C2H4, C2H2) -> (expected code triple, expected fault)
        ((100, 50, 2000, 100, 1), (0, 0, 0), "Normal"),
        ((100, 5, 2000, 100, 1), (0, 1, 0), "PD"),
        ((100, 5, 2000, 100, 50), (1, 1, 0), "PD"),
        ((100, 50, 100, 200, 50), (1, 0, 1), "D1"),
        ((100, 50, 20, 100, 50), (1, 0, 2), "D2"),
        ((100, 50, 50, 100, 1), (0, 0, 1), "T1"),
        ((100, 200, 2000, 100, 1), (0, 2, 0), "T1"),
        ((100, 200, 50, 100, 1), (0, 2, 1), "T2"),
        ((100, 200, 20, 100, 1), (0, 2, 2), "T3"),
    ]

    def test_all_canonical_entries(self):
        for gases, triple, fault in self.CASES:
            s = S(h2=float(gases[0]), ch4=float(gases[1]), c2h6=float(gases[2]),
                  c2h4=float(gases[3]), c2h2=float(gases[4]))
            self.assertEqual(_triple(s), triple, "gases={}".format(gases))
            res = iec_three_ratio(s)
            self.assertTrue(res.applicable, "gases={}".format(gases))
            self.assertEqual(res.code, fault, "gases={}".format(gases))

    def test_undocumented_triple_is_no_decision(self):
        # (2, 0, 1) is listed ambiguously in some sources; we refuse to guess.
        s = S(h2=100.0, ch4=50.0, c2h6=50.0, c2h4=100.0, c2h2=400.0)
        self.assertEqual(_triple(s), (2, 0, 1))
        res = iec_three_ratio(s)
        self.assertEqual(res.code, "ND")
        self.assertFalse(res.applicable)

    def test_table_has_nine_entries(self):
        self.assertEqual(len(IEC_FAULT_TABLE), 9)

    def test_missing_ratio_returns_na(self):
        s = S(h2=0.0)
        self.assertEqual(iec_three_ratio(s).code, "N/A")


class TestIECDirectRatio(unittest.TestCase):
    def test_pd(self):
        self.assertEqual(iec_ratio(S(h2=1000.0, ch4=10.0, c2h6=1000.0, c2h4=100.0, c2h2=1.0)).code, "PD")

    def test_t3(self):
        # r2 < 0.2, r1 > 1, r5 > 4
        s = S(h2=10.0, ch4=100.0, c2h6=10.0, c2h4=100.0, c2h2=1.0)
        self.assertEqual(iec_ratio(s).code, "T3")

    def test_no_decision(self):
        s = S(h2=100.0, ch4=100.0, c2h6=100.0, c2h4=100.0, c2h2=100.0)
        self.assertEqual(iec_ratio(s).code, "ND")


class TestRogers(unittest.TestCase):
    def test_normal(self):
        s = S(h2=100.0, ch4=50.0, c2h6=200.0, c2h4=100.0, c2h2=1.0)
        self.assertEqual(rogers_ratio(s).code, "Normal")

    def test_pd(self):
        s = S(h2=1000.0, ch4=10.0, c2h6=200.0, c2h4=100.0, c2h2=1.0)
        self.assertEqual(rogers_ratio(s).code, "PD")

    def test_no_decision_when_undefined_ratio(self):
        s = S(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0)
        self.assertEqual(rogers_ratio(s).code, "N/A")


class TestDoernenburg(unittest.TestCase):
    def test_requires_co(self):
        s = S(h2=5000.0, ch4=5000.0, c2h6=5000.0, c2h4=5000.0, c2h2=5000.0)
        self.assertEqual(doernenburg(s).code, "N/A")

    def test_no_fault_when_below_limits(self):
        # all ratios defined, but nothing exceeds 2x the Doernenburg limits
        s = S(h2=10.0, ch4=10.0, c2h6=10.0, c2h4=10.0, c2h2=1.0, co=10.0)
        self.assertEqual(doernenburg(s).code, "No fault")

    def test_na_when_ratio_undefined(self):
        # C2H2 = 0 makes C2H6/C2H2 and C2H2/CH4 undefined -> N/A, not 'No fault'
        s = S(h2=10.0, ch4=10.0, c2h6=10.0, c2h4=10.0, c2h2=0.0, co=10.0)
        self.assertEqual(doernenburg(s).code, "N/A")


class TestDuvalTriangle(unittest.TestCase):
    """Each of the seven zones must be hit by a representative point."""

    ZONE_POINTS = [
        # (CH4, C2H2, C2H4) -> expected zone
        ((99.0, 0.5, 0.5), "PD"),
        ((85.0, 2.0, 13.0), "T1"),
        ((63.0, 2.0, 35.0), "T2"),
        ((10.0, 5.0, 85.0), "T3"),
        ((20.0, 60.0, 20.0), "D1"),
        ((20.0, 40.0, 40.0), "D2"),
        ((20.0, 20.0, 60.0), "DT"),
    ]

    def test_all_seven_zones(self):
        for gases, zone in self.ZONE_POINTS:
            s = S(ch4=float(gases[0]), c2h2=float(gases[1]), c2h4=float(gases[2]))
            res = duval_triangle1(s)
            self.assertEqual(res.code, zone, "point={}".format(gases))
            self.assertTrue(res.applicable)

    def test_apex_points(self):
        self.assertEqual(duval_triangle1(S(ch4=100.0, c2h2=0.0, c2h4=0.0)).code, "PD")
        self.assertEqual(duval_triangle1(S(ch4=0.0, c2h2=100.0, c2h4=0.0)).code, "D1")
        self.assertEqual(duval_triangle1(S(ch4=0.0, c2h2=0.0, c2h4=100.0)).code, "T3")

    def test_degenerate_zero_sum(self):
        s = S(ch4=0.0, c2h2=0.0, c2h4=0.0)
        res = duval_triangle1(s)
        self.assertEqual(res.code, "N/A")
        self.assertFalse(res.applicable)

    def test_missing_gas(self):
        s = GasSample(h2=1.0, ch4=None, c2h6=1.0, c2h4=1.0, c2h2=1.0)
        self.assertEqual(duval_triangle1(s).code, "N/A")


class TestValidation(unittest.TestCase):
    def test_negative_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4=-1.0))

    def test_nan_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4=float("nan")))

    def test_inf_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4=float("inf")))

    def test_bool_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4=True))

    def test_string_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4="50"))

    def test_missing_required_gas(self):
        s = GasSample(h2=1.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=None)
        with self.assertRaises(MissingGasError):
            validate(s)

    def test_implausible_magnitude_rejected(self):
        with self.assertRaises(DGAValidationError):
            validate(S(ch4=1.0e9))

    def test_optional_gases_not_required(self):
        s = GasSample(h2=1.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=1.0)  # co/co2 None
        validate(s)

    def test_wrong_type(self):
        with self.assertRaises(DGAValidationError):
            validate("not a sample")


class TestSentinelZeros(unittest.TestCase):
    def test_detects_tiny_values(self):
        s = S(c2h2=1e-4)
        self.assertIn("c2h2", flag_sentinel_zeros(s))

    def test_ignores_real_values(self):
        self.assertEqual(flag_sentinel_zeros(S()), [])

    def test_exactly_zero_not_flagged(self):
        # a hard 0 is a different problem (undefined ratio), not a sentinel
        self.assertNotIn("c2h2", flag_sentinel_zeros(S(c2h2=0.0)))


class TestDiagnose(unittest.TestCase):
    def test_default_methods_all_present(self):
        res = diagnose(S())
        names = set(r.method for r in res.results)
        self.assertEqual(names, {"iec_three_ratio", "iec_ratio", "rogers_ratio", "duval_triangle1"})

    def test_explicit_subset(self):
        res = diagnose(S(), methods=("duval_triangle1",))
        self.assertEqual(len(res.results), 1)

    def test_unknown_method_raises(self):
        with self.assertRaises(KeyError):
            diagnose(S(), methods=("nope",))


class TestZeroDependency(unittest.TestCase):
    """Guards the property that makes embedded deployment possible."""

    def test_no_third_party_modules(self):
        import dga_core  # noqa: F401
        banned = {"numpy", "pandas", "matplotlib", "scipy", "plotly", "sklearn"}
        loaded = set(m.split(".")[0] for m in sys.modules)
        self.assertEqual(loaded & banned, set())

    def test_registry_methods_cover_defaults(self):
        for name in ("iec_three_ratio", "iec_ratio", "rogers_ratio", "duval_triangle1"):
            self.assertIn(name, METHOD_REGISTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
