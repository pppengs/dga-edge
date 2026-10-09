# -*- coding: utf-8 -*-
"""tools/check_py36_compat.py

Static check that the deployable packages stay importable on CPython 3.6.

Jetson Nano (2019) tops out at JetPack 4.6.4, which ships Python 3.6. We cannot
flash a board in CI, so this AST pass is the substitute: it rejects syntax and
stdlib imports that only exist in later versions.

Run:  python tools/check_py36_compat.py dga_core dga_service
Exit code 1 if any violation is found.
"""

import ast
import os
import sys

# feature -> (introduced in, human note)
MIN_VERSION = {
    "f-string": "3.6 (ok)",
    "variable annotation": "3.6 (ok)",
}

# attr -> python version where it became available
STDLIB_MIN = {
    "dataclasses": "3.7",
    "contextvars": "3.7",
    "importlib.resources": "3.7",
    "graphlib": "3.9",
    "zoneinfo": "3.9",
}

BUILTIN_GENERICS = {"list", "dict", "set", "tuple", "frozenset", "type"}


class Checker(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.problems = []

    def _flag(self, node, version, message):
        self.problems.append((getattr(node, "lineno", 0), version, message))

    # -- syntax that does not parse at all on 3.6 is caught by the compile step
    def visit_NamedExpr(self, node):
        self._flag(node, "3.8", "walrus operator ':=' ")
        self.generic_visit(node)

    def visit_Match(self, node):
        self._flag(node, "3.10", "match statement")
        self.generic_visit(node)

    def visit_TryStar(self, node):
        self._flag(node, "3.11", "except* groups")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        # PEP 526 variable annotations are 3.6+, but PEP 563 evaluation of
        # annotations in class bodies can still bite; only flag subscripts.
        self.generic_visit(node)

    def visit_Subscript(self, node):
        # list[str] style builtin generics are 3.9+ even inside annotations,
        # unless `from __future__ import annotations` is present.
        if isinstance(node.value, ast.Name) and node.value.id in BUILTIN_GENERICS:
            self._flag(node, "3.9",
                       "builtin generic '{}[...]' (use typing.List/Dict on 3.6)".format(
                           node.value.id))
        self.generic_visit(node)

    def visit_JoinedStr(self, node):
        # self-documenting f-strings (f"{x=}") are 3.8+
        for value in node.values:
            if isinstance(value, ast.FormattedValue) and value.conversion == 0:
                pass
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in STDLIB_MIN:
                self._flag(node, STDLIB_MIN[top], "import '{}'".format(alias.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            top = node.module.split(".")[0]
            if top in STDLIB_MIN:
                self._flag(node, STDLIB_MIN[top], "from '{}' import".format(node.module))
        self.generic_visit(node)

    def visit_arguments(self, node):
        if getattr(node, "posonlyargs", None):
            self._flag(node, "3.8", "positional-only parameters ('/')")
        self.generic_visit(node)


def _collect_fstring_literals(tokens, source):
    """Yield (lineno, literal_text) for every f-string literal in a token stream.

    Tokenising rather than regexing the raw source is what keeps this checker
    from flagging its own message strings. It also has to cope with two very
    different tokenisations:

      * Python < 3.12  - an f-string is a single STRING token.
      * Python >= 3.12 - PEP 701 splits it up, and crucially the *expression*
        parts become ordinary NAME/OP tokens; FSTRING_MIDDLE only carries the
        literal text. Rebuilding from FSTRING_START/MIDDLE/END therefore
        reconstructs "f\"\"" for f"{x=}" - it silently detects nothing. The text
        must instead be sliced out of the source between FSTRING_START.start and
        FSTRING_END.end.

    Getting this wrong is worse than a false positive: the gate would report OK
    while checking nothing.
    """
    import tokenize

    lines = source.splitlines(True)
    start = None
    for tok in tokens:
        name = tokenize.tok_name.get(tok.type, "")
        if name == "FSTRING_START":
            start = tok.start
            continue
        if name == "FSTRING_END" and start is not None:
            end = tok.end
            if start[0] == end[0]:
                text = lines[start[0] - 1][start[1]:end[1]]
            else:
                parts = [lines[start[0] - 1][start[1]:]]
                for lineno in range(start[0], end[0] - 1):
                    parts.append(lines[lineno])
                parts.append(lines[end[0] - 1][:end[1]])
                text = "".join(parts)
            yield (start[0], text)
            start = None
            continue
        if tok.type == tokenize.STRING:
            yield (tok.start[0], tok.string)


def _is_self_documenting(body):
    """True when an f-string body uses the 3.8 ``{expr=}`` debug specifier."""
    i = 0
    while i < len(body):
        if body[i] != "{":
            i += 1
            continue
        j = body.find("}", i)
        if j == -1:
            return False
        inner = body[i + 1:j]
        if inner:
            # Strip a trailing conversion (!r/!s/!a) and format spec (:...) so
            # that f"{x=!r}" and f"{x=:>10}" are recognised too.
            head = inner.split("!")[0].split(":")[0]
            # "=" must be the debug marker, not part of a comparison or keyword
            # argument. f"{a == b}" and f"{f(x=1)}" are both legal pre-3.8.
            if (head.endswith("=")
                    and not head.endswith("==")
                    and not head.endswith("!=")
                    and not head.endswith(">=")
                    and not head.endswith("<=")
                    and "==" not in head
                    and "<=" not in head
                    and ">=" not in head
                    and "!=" not in head):
                return True
        i = j + 1
    return False


def check_string_features(source, path, problems):
    """Things that are easier to spot textually than via AST."""
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return

    for lineno, literal in _collect_fstring_literals(tokens, source):
        prefix_end = 0
        while prefix_end < len(literal) and literal[prefix_end] not in "'\"":
            prefix_end += 1
        if "f" not in literal[:prefix_end].lower():
            continue
        if _is_self_documenting(literal[prefix_end:]):
            problems.append(
                (lineno, "3.8",
                 "self-documenting f-string (f'{x=}') - not valid before "
                 "Python 3.8"))


def check_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [(exc.lineno or 0, "?", "SYNTAX ERROR: {}".format(exc.msg))]

    checker = Checker(path)
    checker.visit(tree)
    check_string_features(source, path, checker.problems)
    return checker.problems


def check_package(root):
    problems = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                p = os.path.join(dirpath, fn)
                for lineno, version, msg in check_file(p):
                    problems.append((p, lineno, version, msg))
    return problems


def _display(path, root):
    """Make a path readable without ever raising.

    os.path.relpath raises ValueError when the two paths are on different
    Windows drives, which turns "check this directory" into a crash.
    """
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return os.path.abspath(path)
    return path if rel.startswith("..") else rel


def main(argv):
    targets = argv[1:] or ["dga_core", "dga_service"]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    total = 0
    for target in targets:
        # An absolute path outside the repo is legitimate (checking a candidate
        # snippet before pasting it in), so fall back to using it as given.
        path = target if os.path.isabs(target) else os.path.join(root, target)
        if not os.path.isdir(path):
            print("skip {}: not a directory".format(target))
            continue
        problems = check_package(path)
        print("=== {} ===".format(target))
        if not problems:
            print("    OK - no Python 3.7+ features detected")
        for p, lineno, version, msg in problems:
            print("    {}:{}  requires Python {}  -> {}".format(
                _display(p, root), lineno, version, msg))
            total += 1
    print("")
    print("total violations: {}".format(total))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
