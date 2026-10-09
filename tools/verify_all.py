# -*- coding: utf-8 -*-
"""tools/verify_all.py

One command that runs every gate the CI enforces, locally, and prints a single
pass/fail summary. This exists because the deployment contract has no hardware
behind it: the substitute for "does it run on the board?" is a fixed set of
static and dynamic checks, and they should be runnable with one command.

Gates:
  1. unit tests (zero third-party dependencies installed)
  2. Python 3.6 grammar check on the deployable packages
  3. third-party import scan on the deployable packages
  4. zero-runtime-dependency re-check with a poisoned sys.path
  5. optional: dataset validation + condition experiment + benchmarks

Usage:
    python tools/verify_all.py            # static gates only (fast, no network)
    python tools/verify_all.py --full     # also run the experiments
"""

import argparse
import ast
import importlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DEPLOYABLE = ("dga_core", "dga_service")
# Only the deployable packages are under a hard 3.6 grammar contract. The rest
# are checked too, because they run on the same interpreter in CI and a stray
# 3.12-only construct there would break the matrix build.
PY36_CHECKED = DEPLOYABLE + ("tests", "experiments", "tools")

BANNED = {
    "numpy", "pandas", "matplotlib", "scipy", "plotly", "sklearn",
    "openpyxl", "requests", "pytest", "dateutil", "numba", "torch",
}

# Modules the stdlib itself pulls in when importing the packages. Anything not
# in BANNED is allowed, but a non-stdlib top-level module here would show up as
# a leak on a bare Python 3.6 install.
ALLOWED_NON_STDLIB = set()


def _run(label, argv):
    print("=" * 72)
    print(label)
    print("=" * 72)
    proc = subprocess.run(argv, cwd=ROOT)
    ok = proc.returncode == 0
    print("-> {}".format("PASS" if ok else "FAIL"))
    print("")
    return ok


def scan_imports():
    """Walk the deployable packages and classify every imported top-level name."""
    found = {}
    for pkg in DEPLOYABLE:
        for root, _dirs, files in os.walk(os.path.join(ROOT, pkg)):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as fh:
                    try:
                        tree = ast.parse(fh.read(), path)
                    except SyntaxError as exc:
                        return None, "{}: {}".format(path, exc)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            found.setdefault(alias.name.split(".")[0], []).append(path)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        # A relative import (from .methods import ...) has
                        # level > 0 and refers to a sibling module in this
                        # package, not a top-level distribution.
                        if getattr(node, "level", 0):
                            continue
                        found.setdefault(node.module.split(".")[0], []).append(path)
    return found, None


def gate_import_scan():
    print("=" * 72)
    print("Gate 3: third-party import scan")
    print("=" * 72)
    found, err = scan_imports()
    if err:
        print("FAIL: syntax error {}\n".format(err))
        return False

    violations = sorted(set(found) & BANNED)
    for mod in violations:
        print("  BANNED {:<12} used by {}".format(mod, ", ".join(sorted(set(found[mod])))))
    if violations:
        print("-> FAIL")
        print("")
        return False

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    local = set(DEPLOYABLE) | {os.path.splitext(f)[0] for f in os.listdir(ROOT)
                              if f.endswith(".py")}
    unknown = sorted(m for m in found
                     if m not in BANNED and m not in stdlib and m not in local
                     and m not in ALLOWED_NON_STDLIB)
    print("  imported top-level modules: {}".format(", ".join(sorted(found))))
    if unknown:
        print("  NOT a known stdlib module: {}".format(", ".join(unknown)))
        print("  (verify these by hand - Python 3.6 on the board has less stdlib)")
        print("-> WARN (not a failure)")
    else:
        print("  all imports resolve to the standard library")
    print("-> PASS")
    print("")
    return True


def gate_zero_dependency():
    """Import the deployable packages in a subprocess that blocks site-packages.

    This is the real test: not "do the imports look clean" but "does the package
    import with nothing installed".
    """
    print("=" * 72)
    print("Gate 4: import with site-packages disabled")
    print("=" * 72)
    code = (
        "import sys, importlib\n"
        "sys.path = [p for p in sys.path "
        "if 'site-packages' not in p and 'dist-packages' not in p]\n"
        "for pkg in {pkgs!r}:\n"
        "    m = importlib.import_module(pkg)\n"
        "    print('  imported', pkg, 'from', m.__file__)\n"
        "from dga_core import GasSample, diagnose, monitor\n"
        "s = GasSample(h2=100.0, ch4=200.0, c2h6=50.0, c2h4=100.0, c2h2=1.0, co=120.0)\n"
        "assert len(diagnose(s).results) >= 4\n"
        "assert monitor(s).condition in (1, 2, 3, 4)\n"
        "print('  diagnosis + condition monitoring OK')\n"
    ).format(pkgs=list(DEPLOYABLE))
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        print("-> FAIL")
        print("")
        return False
    print("-> PASS")
    print("")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--full", action="store_true",
                        help="also run dataset validation, condition experiment "
                             "and the benchmark (needs the .cache/ datasets)")
    parser.add_argument("--bench", action="store_true",
                        help="also run the latency benchmark")
    args = parser.parse_args()

    results = []
    results.append(("unit tests",
                    _run("Gate 1: unit tests",
                         [sys.executable, "-m", "unittest", "discover", "-s", "tests"])))
    results.append(("py3.6 grammar",
                    _run("Gate 2: Python 3.6 grammar check",
                         [sys.executable, "tools/check_py36_compat.py"]
                         + list(PY36_CHECKED))))
    results.append(("import scan", gate_import_scan()))
    results.append(("zero dependency", gate_zero_dependency()))

    if args.full or args.bench:
        results.append(("benchmark",
                        _run("Gate 5: latency / memory benchmark",
                             [sys.executable, "-m", "experiments.run_benchmark",
                              "--tag", "verify"])))
    if args.full:
        results.append(("validation",
                        _run("Gate 6: multi-dataset method validation",
                             [sys.executable, "-m", "experiments.run_validation"])))
        results.append(("condition",
                        _run("Gate 7: condition grading vs. labels",
                             [sys.executable, "-m", "experiments.run_condition"])))

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    width = max(len(name) for name, _ in results)
    for name, ok in results:
        print("  {:<{w}}  {}".format(name, "PASS" if ok else "FAIL", w=width))
    failed = [n for n, ok in results if not ok]
    print("")
    if failed:
        print("FAILED: {}".format(", ".join(failed)))
        return 1
    print("all gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
