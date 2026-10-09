# -*- coding: utf-8 -*-
"""Tests for dga_service (batch pipeline, IO, CLI).

These exercise the layer that ships to the board, so they must keep passing
without any third-party package installed.
"""

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from dga_core.models import GasSample  # noqa: E402
from dga_service import io_utils, pipeline  # noqa: E402
from dga_service.cli import main as cli_main  # noqa: E402

TMP = None


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="dga-test-")


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, ignore_errors=True)


def write_csv(name, rows):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


BASIC_HEADER = ["id", "H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"]
BASIC_ROWS = [
    BASIC_HEADER,
    ["A", 100, 50, 30, 20, 1, 100, 1000],
    ["B", 5000, 10, 1000, 100, 2, 50, 800],
    ["C", 100, 50, 2000, 100, 1, 50, 800],
]


class TestReadCsv(unittest.TestCase):
    def test_reads_and_normalises_columns(self):
        path = write_csv("basic.csv", BASIC_ROWS)
        samples, errors = io_utils.read_csv(path)
        self.assertEqual(errors, [])
        self.assertEqual(len(samples), 3)
        sample, row, stamp = samples[0]
        self.assertEqual(sample.sample_id, "A")
        self.assertEqual(sample.h2, 100.0)
        self.assertIsNone(stamp)

    def test_chinese_headers_and_messy_names(self):
        rows = [["编号", "氢气", "甲烷", "乙烷", "乙烯", "乙炔", "一氧化碳", "二氧化碳"],
                ["X-1", "120", "60", "30", "20", "0", "100", "1000"]]
        path = write_csv("cn.csv", rows)
        samples, errors = io_utils.read_csv(path)
        self.assertEqual(errors, [])
        self.assertEqual(samples[0][0].h2, 120.0)
        self.assertEqual(samples[0][0].sample_id, "X-1")

    def test_compound_id_aliases(self):
        # _norm() collapses underscores, so "unit_id" must still match
        for alias in ("unit_id", "sample_id", "transformer_id", "device id"):
            rows = [[alias, "H2", "CH4", "C2H6", "C2H4", "C2H2"],
                    ["T-9", 10, 10, 10, 10, 0]]
            path = write_csv("alias.csv", rows)
            samples, _ = io_utils.read_csv(path)
            self.assertEqual(samples[0][0].sample_id, "T-9", alias)

    def test_blank_and_na_cells_become_none(self):
        rows = [BASIC_HEADER, ["A", "", "N/A", "50", "-", "1", "100", "1000"]]
        path = write_csv("blank.csv", rows)
        samples, _ = io_utils.read_csv(path)
        s = samples[0][0]
        self.assertIsNone(s.h2)
        self.assertIsNone(s.ch4)
        self.assertEqual(s.c2h6, 50.0)

    def test_unparseable_cell_is_reported_not_dropped(self):
        rows = [BASIC_HEADER, ["A", "abc", "50", "30", "20", "1", "100", "1000"],
                ["B", "100", "50", "30", "20", "1", "100", "1000"]]
        path = write_csv("bad.csv", rows)
        samples, errors = io_utils.read_csv(path)
        self.assertEqual(len(samples), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("abc", errors[0])

    def test_rejects_header_with_no_gas_column(self):
        path = write_csv("nogas.csv", [["foo", "bar"], ["1", "2"]])
        with self.assertRaises(Exception):
            io_utils.read_csv(path)


class TestParseDate(unittest.TestCase):
    def test_accepted_formats(self):
        cases = [
            ("2025-01-15", datetime(2025, 1, 15)),
            ("2025-01-15 08:30:00", datetime(2025, 1, 15, 8, 30, 0)),
            ("2025/01/15", datetime(2025, 1, 15)),
            ("20250115", datetime(2025, 1, 15)),
            ("2025.01.15", datetime(2025, 1, 15)),
        ]
        for text, expected in cases:
            self.assertEqual(io_utils.parse_date(text), expected, text)

    def test_unparseable_returns_none(self):
        for text in ("", "not a date", None, "15 Jan 2025"):
            self.assertIsNone(io_utils.parse_date(text), text)


class TestSeries(unittest.TestCase):
    ROWS = [
        ["id", "date", "H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"],
        ["T-1", "2025-01-01", 100, 50, 30, 20, 0, 100, 1000],
        ["T-1", "2025-07-01", 110, 55, 32, 22, 0.5, 110, 1100],
        ["T-2", "2025-01-01", 80, 20, 10, 15, 0, 90, 1200],
    ]

    def test_groups_and_sorts_by_time(self):
        path = write_csv("series.csv", self.ROWS)
        series, errors = io_utils.read_csv_series(path)
        self.assertEqual(sorted(series.keys()), ["T-1", "T-2"])
        self.assertEqual(len(series["T-1"]), 2)
        self.assertLess(series["T-1"][0][0], series["T-1"][1][0])
        self.assertEqual(errors, [])

    def test_rows_without_dates_are_excluded_and_reported(self):
        rows = [list(r) for r in self.ROWS]
        rows.append(["T-3", "sometime", 10, 10, 10, 10, 0, 10, 100])
        path = write_csv("series_bad.csv", rows)
        series, errors = io_utils.read_csv_series(path)
        self.assertNotIn("T-3", series)
        self.assertTrue(any("T-3" in e for e in errors))

    def test_trend_escalates_on_rate(self):
        path = write_csv("series2.csv", self.ROWS)
        series, _ = io_utils.read_csv_series(path)
        statuses = pipeline.run_trend(series)
        by_id = dict((s.sample_id, s) for s in statuses)
        # T-1: H2 100 -> 110 over 181 days is a small drift, but C2H2 goes
        # 0 -> 0.5, and "any increase" on acetylene is significant.
        self.assertTrue(by_id["T-1"].rate.significant)
        self.assertIn("C2H2", by_id["T-1"].rate.exceeding_table3)
        # T-2 has only one point, so no rate is computed
        self.assertIsNone(by_id["T-2"].rate)

    def test_trend_handles_duplicate_timestamps(self):
        rows = [list(r) for r in self.ROWS]
        rows[2][1] = "2025-01-01"   # T-1 second sample now shares the date
        path = write_csv("series_dup.csv", rows)
        series, _ = io_utils.read_csv_series(path)
        statuses = pipeline.run_trend(series)
        by_id = dict((s.sample_id, s) for s in statuses)
        # Must not raise, and must fall back to the absolute assessment
        self.assertIsNone(by_id["T-1"].rate)


class TestPipeline(unittest.TestCase):
    def test_bad_row_does_not_abort_the_batch(self):
        samples = [
            GasSample(100.0, 50.0, 30.0, 20.0, 1.0, sample_id="ok-1"),
            GasSample(-5.0, 50.0, 30.0, 20.0, 1.0, sample_id="bad-negative"),
            GasSample(100.0, 50.0, 30.0, 20.0, 1.0, sample_id="ok-2"),
        ]
        report = pipeline.run_batch(samples)
        self.assertEqual(len(report.results), 2)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], "bad-negative")

    def test_bare_samples_and_tuples_are_both_accepted(self):
        bare = GasSample(100.0, 50.0, 30.0, 20.0, 1.0, sample_id="a")
        self.assertIs(pipeline._unwrap(bare), bare)
        self.assertIs(pipeline._unwrap((bare, "raw", None)), bare)

    def test_condition_is_attached(self):
        samples = [GasSample(3000.0, 50.0, 30.0, 20.0, 1.0, co=100.0,
                             sample_id="hot")]
        report = pipeline.run_batch(samples)
        self.assertEqual(len(report.conditions), 1)
        self.assertEqual(report.conditions[0].condition, 4)
        self.assertEqual(report.condition_counts()[4], 1)

    def test_condition_can_be_disabled(self):
        samples = [GasSample(100.0, 50.0, 30.0, 20.0, 1.0, co=100.0,
                             sample_id="fine")]
        report = pipeline.run_batch(samples, with_condition=False)
        self.assertEqual(report.conditions, [])


class TestExport(unittest.TestCase):
    def test_rows_carry_condition_columns(self):
        samples = [GasSample(3000.0, 50.0, 30.0, 20.0, 1.0, co=100.0,
                             sample_id="hot")]
        report = pipeline.run_batch(samples)
        rows = io_utils.results_to_rows(report.results, conditions=report.conditions)
        self.assertEqual(rows[0]["condition"], 4)
        self.assertEqual(rows[0]["condition_label"], "Critical")
        self.assertEqual(rows[0]["limiting_gas"], "H2")

    def test_jsonl_carries_condition_block(self):
        samples = [GasSample(3000.0, 50.0, 30.0, 20.0, 1.0, co=100.0,
                             sample_id="hot")]
        report = pipeline.run_batch(samples)
        path = os.path.join(TMP, "out.jsonl")
        io_utils.write_jsonl(path, report.results, conditions=report.conditions)
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.loads(fh.readline())
        self.assertEqual(payload["condition"]["condition"], 4)
        self.assertEqual(payload["condition"]["label"], "Critical")


def run_cli(argv):
    """Invoke the CLI with its chatter captured, so test output stays readable."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        return cli_main(argv)


class TestCli(unittest.TestCase):
    def test_end_to_end_writes_outputs(self):
        src = write_csv("cli_in.csv", BASIC_ROWS)
        out_csv = os.path.join(TMP, "cli_out.csv")
        out_jsonl = os.path.join(TMP, "cli_out.jsonl")
        rc = run_cli(["--input", src, "--output", out_csv, "--jsonl", out_jsonl,
                      "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out_csv))
        self.assertTrue(os.path.exists(out_jsonl))
        with open(out_csv, "r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 3)
        self.assertIn("condition", rows[0])

    def test_trend_mode(self):
        src = write_csv("cli_series.csv", TestSeries.ROWS)
        out_csv = os.path.join(TMP, "cli_trend.csv")
        rc = run_cli(["--input", src, "--trend", "--output", out_csv, "--quiet"])
        self.assertEqual(rc, 0)
        with open(out_csv, "r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(sorted(r["sample_id"] for r in rows), ["T-1", "T-2"])
        self.assertIn("interval_days", rows[0])

    def test_missing_input_returns_2(self):
        self.assertEqual(run_cli(["--input", os.path.join(TMP, "nope.csv")]), 2)

    def test_no_condition_flag(self):
        src = write_csv("cli_nocond.csv", BASIC_ROWS)
        out_csv = os.path.join(TMP, "cli_nocond_out.csv")
        rc = run_cli(["--input", src, "--no-condition", "--output", out_csv,
                      "--quiet"])
        self.assertEqual(rc, 0)
        with open(out_csv, "r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertNotIn("condition", rows[0])


if __name__ == "__main__":
    unittest.main()
