# -*- coding: utf-8 -*-
"""Tests for dga_core.condition (IEEE C57.104-2019 condition monitoring).

Runs on Python 3.6+ with the standard library only.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dga_core.models import GasSample  # noqa: E402
from dga_core.tables import (  # noqa: E402
    IEEE_C57_104_TABLE1, IEEE_TDCG_LIMITS, TDCG_GAS_KEYS,
)
from dga_core.condition import (  # noqa: E402
    assess_condition, assess_rate, monitor, total_dissolved_combustible_gas,
)


def S(**kw):
    return GasSample(**kw)


class TestTDCG(unittest.TestCase):
    def test_tdcg_excludes_co2(self):
        s = S(h2=1.0, ch4=2.0, c2h6=4.0, c2h4=8.0, c2h2=16.0, co=32.0, co2=9999.0)
        tdcg, complete = total_dissolved_combustible_gas(s)
        self.assertTrue(complete)
        self.assertAlmostEqual(tdcg, 63.0)

    def test_tdcg_incomplete_without_co(self):
        s = S(h2=1.0, ch4=2.0, c2h6=4.0, c2h4=8.0, c2h2=16.0)
        tdcg, complete = total_dissolved_combustible_gas(s)
        self.assertFalse(complete)
        self.assertAlmostEqual(tdcg, 31.0)

    def test_tdcg_keys(self):
        self.assertEqual(set(TDCG_GAS_KEYS),
                         set(["H2", "CH4", "C2H6", "C2H4", "C2H2", "CO"]))
        self.assertNotIn("CO2", TDCG_GAS_KEYS)


class TestConditionTable1(unittest.TestCase):
    """Every Table 1 boundary must land on the documented condition."""

    def test_boundaries_for_each_gas(self):
        for gas, (c1, c2, c3) in IEEE_C57_104_TABLE1.items():
            attr = {"H2": "h2", "CH4": "ch4", "C2H6": "c2h6", "C2H4": "c2h4",
                    "C2H2": "c2h2", "CO": "co", "CO2": "co2"}[gas]
            base = dict(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)

            def cond_for(v):
                d = dict(base)
                d[attr] = v
                return assess_condition(S(**d)).per_gas_dict()[gas]

            self.assertEqual(cond_for(c1), 1, "{} at c1".format(gas))
            self.assertEqual(cond_for(c2), 2, "{} at c2".format(gas))
            self.assertEqual(cond_for(c3), 3, "{} at c3".format(gas))
            # a hair above c3 must be condition 4; a hair above c1/c2 must step up
            self.assertEqual(cond_for(c3 + 1e-6), 4, "{} above c3".format(gas))
            self.assertEqual(cond_for(c1 + 1e-6), 2, "{} above c1".format(gas))
            self.assertEqual(cond_for(c2 + 1e-6), 3, "{} above c2".format(gas))

    def test_tdcg_at_c1_column_sum_is_still_condition_1(self):
        # Every gas sitting exactly at its own condition-1 limit:
        # 100 + 120 + 65 + 50 + 1 + 350 = 686 ppm, and 686 <= 720 -> condition 1.
        s = S(h2=100.0, ch4=120.0, c2h6=65.0, c2h4=50.0, c2h2=1.0, co=350.0, co2=0.0)
        a = assess_condition(s)
        self.assertAlmostEqual(a.tdcg, 686.0)
        self.assertEqual(a.tdcg_condition, 1)
        self.assertEqual(a.condition, 1)
        self.assertEqual(a.limiting_gas, None)

    def test_tdcg_limit_is_not_the_column_sum(self):
        """The standard's TDCG limits are NOT the sum of its per-gas limits.

        Guards against a well-meaning "correction" that recomputes TDCG limits
        as the column sum. See docs/STANDARDS.md.
        """
        for k, tdcg_limit in enumerate(IEEE_TDCG_LIMITS):
            column_sum = sum(limits[k] for limits in (
                IEEE_C57_104_TABLE1[g] for g in TDCG_GAS_KEYS))
            self.assertLess(column_sum, tdcg_limit,
                            "column sum {} should stay below TDCG limit {}".format(
                                column_sum, tdcg_limit))

    def test_tdcg_never_raises_the_condition(self):
        """Property: under Table 1, TDCG can never be the limiting factor.

        Because sum(per-gas Ck limit) < TDCG Ck limit for every k, a sample
        whose worst per-gas condition is k always has TDCG below the Ck TDCG
        limit. This holds for any non-negative gas vector.
        """
        import random
        rng = random.Random(20261001)
        for _ in range(2000):
            vals = dict(
                h2=rng.uniform(0, 3000), ch4=rng.uniform(0, 1500),
                c2h6=rng.uniform(0, 300), c2h4=rng.uniform(0, 400),
                c2h2=rng.uniform(0, 60), co=rng.uniform(0, 2000),
                co2=rng.uniform(0, 15000))
            a = assess_condition(S(**vals))
            per_gas_worst = max(c for c in a.per_gas_dict().values() if c is not None)
            self.assertLessEqual(a.tdcg_condition, per_gas_worst)
            self.assertEqual(a.condition, per_gas_worst)
            self.assertNotEqual(a.limiting_gas, "TDCG")

    def test_clean_sample_is_condition_1(self):
        s = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0, co2=500.0)
        a = assess_condition(s)
        self.assertEqual(a.condition, 1)
        self.assertEqual(a.label, "Normal")
        self.assertEqual(a.sampling_interval, "annual")
        self.assertEqual(a.limiting_gas, None)

    def test_single_hot_gas_sets_condition_and_limiting_gas(self):
        # H2 = 800 -> condition 3; everything else tiny
        s = S(h2=800.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=1.0, co2=100.0)
        a = assess_condition(s)
        self.assertEqual(a.condition, 3)
        self.assertEqual(a.limiting_gas, "H2")

    def test_acetylene_is_the_strictest_gas(self):
        # 2 ppm C2H2 is already condition 2, while 2 ppm of anything else is not
        s = S(h2=2.0, ch4=2.0, c2h6=2.0, c2h4=2.0, c2h2=2.0, co=2.0, co2=2.0)
        a = assess_condition(s)
        self.assertEqual(a.limiting_gas, "C2H2")
        self.assertEqual(a.condition, 2)

    def test_condition_4(self):
        s = S(h2=2000.0, ch4=10.0, c2h6=10.0, c2h4=10.0, c2h2=0.0, co=10.0, co2=100.0)
        self.assertEqual(assess_condition(s).condition, 4)
        self.assertEqual(assess_condition(s).label, "Critical")

    def test_missing_co_makes_tdcg_incomplete_and_unrated(self):
        s = S(h2=5000.0, ch4=5000.0, c2h6=5000.0, c2h4=5000.0, c2h2=5000.0)
        a = assess_condition(s)
        self.assertFalse(a.tdcg_complete)
        self.assertIsNone(a.tdcg_condition)
        # per-gas still works
        self.assertEqual(a.condition, 4)

    def test_co2_missing_is_tolerated(self):
        s = S(h2=1.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=1.0)
        a = assess_condition(s)
        self.assertTrue(a.tdcg_complete)
        self.assertEqual(a.condition, 1)


class TestRate(unittest.TestCase):
    def test_rejects_non_positive_interval(self):
        prev = S(h2=10.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=10.0)
        curr = S(h2=20.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=10.0)
        for bad in (0, -1, 0.0):
            with self.assertRaises(ValueError):
                assess_rate(prev, curr, bad)

    def test_rate_scaling(self):
        prev = S(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)
        curr = S(h2=365.25, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)
        r = assess_rate(prev, curr, 365.25)
        # 365.25 ppm over 365.25 days = 1 ppm/day = 365.25 ppm/year
        self.assertAlmostEqual(r.rate_ppm_per_year["H2"], 365.25, places=4)
        self.assertAlmostEqual(r.delta_ppm["H2"], 365.25)

    def test_rate_scaling_half_year(self):
        prev = S(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)
        curr = S(h2=100.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)
        r = assess_rate(prev, curr, 182.625)
        self.assertAlmostEqual(r.rate_ppm_per_year["H2"], 200.0, places=4)

    def test_any_increase_on_acetylene(self):
        prev = S(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.0, co=0.0, co2=0.0)
        curr = S(h2=0.0, ch4=0.0, c2h6=0.0, c2h4=0.0, c2h2=0.001, co=0.0, co2=0.0)
        r = assess_rate(prev, curr, 30.0)
        self.assertIn("C2H2", r.exceeding_table3)
        self.assertIn("C2H2", r.exceeding_table4)
        self.assertTrue(r.significant)

    def test_slow_drift_over_a_year_is_not_significant(self):
        # +1 ppm over a full year is ~1 ppm/year, below every Table 4 limit.
        prev = S(h2=100.0, ch4=100.0, c2h6=100.0, c2h4=100.0, c2h2=5.0, co=100.0, co2=1000.0)
        curr = S(h2=101.0, ch4=101.0, c2h6=101.0, c2h4=101.0, c2h2=5.0, co=101.0, co2=1001.0)
        r = assess_rate(prev, curr, 365.0)
        self.assertFalse(r.significant)
        self.assertEqual(r.exceeding_table3, ())
        self.assertEqual(r.exceeding_table4, ())

    def test_same_drift_over_a_month_is_significant(self):
        # The identical +1 ppm change compressed into 30 days is ~12 ppm/year,
        # which exceeds the CH4 long-period Table 4 limit of 10 ppm/year.
        prev = S(h2=100.0, ch4=100.0, c2h6=100.0, c2h4=100.0, c2h2=5.0, co=100.0, co2=1000.0)
        curr = S(h2=101.0, ch4=101.0, c2h6=101.0, c2h4=101.0, c2h2=5.0, co=101.0, co2=1001.0)
        r = assess_rate(prev, curr, 30.0)
        self.assertTrue(r.significant)
        self.assertIn("CH4", r.exceeding_table4)

    def test_hydrogen_step_exceeds_table3_low_column(self):
        # low O2/N2 column for H2 is 40 ppm; 50 ppm in 30 days must trip
        prev = S(h2=100.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=10.0, co2=100.0)
        curr = S(h2=150.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0, co=10.0, co2=100.0)
        r = assess_rate(prev, curr, 30.0, o2n2_ratio=0.1)
        self.assertIn("H2", r.exceeding_table3)
        # the high-oxygen column is 25 ppm, so it trips there too
        r2 = assess_rate(prev, curr, 30.0, o2n2_ratio=0.5)
        self.assertIn("H2", r2.exceeding_table3)

    def test_missing_gas_is_skipped_not_guessed(self):
        prev = S(h2=100.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0)          # no CO
        curr = S(h2=900.0, ch4=1.0, c2h6=1.0, c2h4=1.0, c2h2=0.0)
        r = assess_rate(prev, curr, 30.0)
        self.assertIsNone(r.delta_ppm["CO"])
        self.assertIsNone(r.rate_ppm_per_year["CO"])
        self.assertNotIn("CO", r.exceeding_table3)


class TestMonitor(unittest.TestCase):
    def test_without_previous_is_plain_assessment(self):
        s = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0, co2=500.0,
              sample_id="T-1")
        m = monitor(s)
        self.assertEqual(m.condition, 1)
        self.assertIsNone(m.rate)
        self.assertFalse(m.rate_escalated)
        self.assertIn("normal operation", m.advice)

    def test_requires_days_when_previous_given(self):
        prev = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0)
        curr = S(h2=20.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0)
        with self.assertRaises(ValueError):
            monitor(curr, previous=prev)

    def test_rate_escalates_by_exactly_one_level(self):
        # absolute levels are condition 1, but C2H2 ticks up -> escalate to 2
        prev = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0, co2=500.0)
        curr = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.5, co=50.0, co2=500.0)
        m = monitor(curr, previous=prev, days=30.0)
        self.assertEqual(m.assessment.condition, 1)
        self.assertTrue(m.rate.significant)
        self.assertTrue(m.rate_escalated)
        self.assertEqual(m.condition, 2)

    def test_escalation_is_capped_at_condition_4(self):
        prev = S(h2=2000.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0, co2=500.0)
        curr = S(h2=2000.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.5, co=50.0, co2=500.0)
        m = monitor(curr, previous=prev, days=30.0)
        self.assertEqual(m.assessment.condition, 4)
        self.assertEqual(m.condition, 4)
        self.assertFalse(m.rate_escalated)

    def test_stable_sample_does_not_escalate(self):
        g = dict(h2=100.0, ch4=50.0, c2h6=30.0, c2h4=20.0, c2h2=0.5, co=100.0, co2=1000.0)
        m = monitor(S(**g), previous=S(**g), days=180.0)
        self.assertFalse(m.rate.significant)
        self.assertFalse(m.rate_escalated)
        self.assertEqual(m.condition, m.assessment.condition)

    def test_as_dict_is_json_friendly(self):
        s = S(h2=10.0, ch4=5.0, c2h6=3.0, c2h4=2.0, c2h2=0.0, co=50.0, co2=500.0)
        d = monitor(s).as_dict()
        self.assertEqual(d["condition"], 1)
        self.assertIsInstance(d["assessment"], dict)
        self.assertIsNone(d["rate"])


if __name__ == "__main__":
    unittest.main()
