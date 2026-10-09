# -*- coding: utf-8 -*-
"""Tests for tools/check_py36_compat.py.

This gate is the CI substitute for owning a Jetson Nano, so a silent regression
in it is expensive: the build stays green while the deployable code stops being
Python 3.6 parseable. These tests exist because that regression actually
happened - the self-documenting f-string check was written against
``tokenize.STRING``, which stopped matching f-strings in Python 3.12 (PEP 701),
so the check detected nothing on modern interpreters.
"""

import io
import importlib.util
import os
import sys
import tokenize
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "check_py36_compat", os.path.join(ROOT, "tools", "check_py36_compat.py"))
c36 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c36)


def fstrings_in(source):
    """Return the f-string literals the checker would extract from source."""
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    return [text for _line, text in c36._collect_fstring_literals(tokens, source)]


def flagged_in(source):
    problems = []
    c36.check_string_features(source, "<test>", problems)
    return problems


class TestFStringExtraction(unittest.TestCase):
    def test_expression_parts_are_reconstructed(self):
        """The core regression: f"{x=}" must come back whole.

        On Python 3.12+ the expression is tokenised as ordinary NAME/OP tokens,
        so rebuilding only from FSTRING_START/MIDDLE/END yields 'f""'.
        """
        src = 'print(f"{x=}")\n'
        self.assertEqual(fstrings_in(src), ['f"{x=}"'])

    def test_plain_literal_middle_is_reconstructed(self):
        src = 'print(f"a={x}")\n'
        self.assertEqual(fstrings_in(src), ['f"a={x}"'])

    def test_non_f_strings_are_ignored_by_the_flag_check(self):
        # A plain str literal mentioning the syntax must never be flagged. This
        # is what made the original checker report itself.
        src = 'msg = "self-documenting f-string (f\'{x=}\')"\n'
        self.assertEqual(flagged_in(src), [])

    def test_comment_mentioning_the_syntax(self):
        src = '# f"{x=}" is a 3.8 feature\n'
        self.assertEqual(flagged_in(src), [])


class TestSelfDocumentingDetection(unittest.TestCase):
    def test_positive_cases(self):
        for src in ('print(f"{x=}")\n',
                    'print(f"{value=:>10}")\n',
                    'print(f"{obj=!r}")\n',
                    'print(f"{a + b=}")\n'):
            with self.subTest(src=src):
                self.assertTrue(flagged_in(src), src)

    def test_negative_cases(self):
        cases = [
            'print(f"a={x}")\n',              # literal '=' then expression
            'print(f"{x}")\n',                # plain expression
            'print(f"{a == b}")\n',           # comparison
            'print(f"{a != b}")\n',
            'print(f"{a >= b}")\n',
            'print(f"{a <= b}")\n',
            'print(f"{f(x=1)}")\n',           # keyword argument
            'print(f"{d[\'k\']}")\n',
            'print(f"no braces here")\n',
            'print("no f-string at all")\n',
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertEqual(flagged_in(src), [], src)

    def test_lineno_is_reported(self):
        src = 'a = 1\nb = 2\nprint(f"{a=}")\n'
        problems = flagged_in(src)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], 3)


class TestOtherGatesStillFire(unittest.TestCase):
    """The walrus / positional-only / 3.7 feature checks must keep working."""

    def _problems_for(self, source):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(source)
            path = fh.name
        try:
            return c36.check_file(path)
        finally:
            os.unlink(path)

    # check_file() yields (lineno, version, message); check_package() prepends
    # the path to make it a 4-tuple.
    def test_walrus_operator_fires(self):
        problems = self._problems_for("if (n := 10) > 5:\n    pass\n")
        self.assertTrue(any(p[1] == "3.8" for p in problems), problems)

    def test_fstring_debug_specifier_fires(self):
        problems = self._problems_for('x = 1\nprint(f"{x=}")\n')
        self.assertTrue(any("self-documenting" in p[2] for p in problems), problems)

    def test_variable_annotations_are_allowed(self):
        # PEP 526 annotations are 3.6; they must NOT be flagged.
        problems = self._problems_for('x: int = 0\ny: str = "a"\n')
        self.assertEqual(problems, [])

    def test_typing_namedtuple_pattern_is_clean(self):
        """The exact workaround the core uses instead of dataclasses."""
        src = ('from typing import NamedTuple, Optional\n\n\n'
               'class S(NamedTuple):\n'
               '    a: Optional[float] = None\n'
               '    b: Optional[float] = None\n\n\n'
               'def f(x):\n'
               '    # type: (S) -> str\n'
               '    return "{}".format(x.a)\n')
        self.assertEqual(self._problems_for(src), [])


class TestCrossDriveRobustness(unittest.TestCase):
    def test_display_never_raises_on_foreign_path(self):
        # relpath raises ValueError across Windows drives; _display must not.
        foreign = "C:\\somewhere\\else\\file.py" if os.name == "nt" else "/else/file.py"
        self.assertIsInstance(c36._display(foreign, ROOT), str)


class TestRepoIsClean(unittest.TestCase):
    def test_deployable_packages_pass(self):
        """The shipped contract: dga_core and dga_service must stay 3.6-clean."""
        for pkg in ("dga_core", "dga_service"):
            problems = c36.check_package(os.path.join(ROOT, pkg))
            self.assertEqual(problems, [], "{}: {}".format(pkg, problems))


if __name__ == "__main__":
    unittest.main()
