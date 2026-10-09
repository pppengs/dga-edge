# -*- coding: utf-8 -*-
"""dga_service.cli

Command line entry point. Standard library only.
"""

import argparse
import os
import sys

def build_parser():
    parser = argparse.ArgumentParser(
        prog="dga-cli",
        description="Batch DGA diagnosis using classical ratio methods.")
    parser.add_argument("--input", "-i", required=True, help="input CSV of DGA samples")
    parser.add_argument("--methods", "-m", default=None,
                        help="comma-separated method names (default: all applicable)")
    parser.add_argument("--output", "-o", default=None, help="output CSV path")
    parser.add_argument("--jsonl", default=None, help="output JSONL path")
    parser.add_argument("--no-validate", action="store_true",
                        help="skip schema validation (not recommended)")
    parser.add_argument("--no-condition", action="store_true",
                        help="skip the IEEE C57.104 condition assessment")
    parser.add_argument("--trend", action="store_true",
                        help="treat the input as a time series: group by id, "
                             "order by date, and evaluate the gas generation "
                             "rate against the previous sample")
    parser.add_argument("--o2n2", type=float, default=None,
                        help="O2/N2 ratio, selects the C57.104 table column "
                             "(<=0.2 uses the sealed-unit column)")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress the summary")
    return parser


def main(argv=None):
    from .io_utils import read_csv, read_csv_series, write_csv, write_jsonl, sentinel_report
    from .pipeline import run_batch, run_trend

    args = build_parser().parse_args(argv)

    if not os.path.exists(args.input):
        print("input not found: {}".format(args.input), file=sys.stderr)
        return 2

    methods = None
    if args.methods:
        methods = tuple(m.strip() for m in args.methods.split(",") if m.strip())

    if args.trend:
        series, errors = read_csv_series(args.input)
        for err in errors:
            print("warn: {}".format(err), file=sys.stderr)
        if not series:
            print("no usable dated samples in {}".format(args.input), file=sys.stderr)
            return 1
        statuses = run_trend(series, o2n2_ratio=args.o2n2)
        latest = [points[-1][1] for points in series.values()]
        report = run_batch(latest, methods=methods,
                           validate_input=not args.no_validate,
                           with_condition=False)
        report.conditions = statuses
    else:
        samples, errors = read_csv(args.input)
        for err in errors:
            print("warn: {}".format(err), file=sys.stderr)
        if not samples:
            print("no usable samples in {}".format(args.input), file=sys.stderr)
            return 1
        report = run_batch(samples, methods=methods,
                           validate_input=not args.no_validate,
                           with_condition=not args.no_condition)

    if args.output:
        write_csv(args.output, _to_rows(report))
        print("wrote {}".format(args.output))
    if args.jsonl:
        write_jsonl(args.jsonl, report.results, conditions=report.conditions)
        print("wrote {}".format(args.jsonl))

    if not args.quiet:
        print("")
        print(report.summary_lines())
        if args.trend:
            print("")
            print("units tracked: {} ({} samples total)".format(
                len(series), sum(len(p) for p in series.values())))
        else:
            n, detail = sentinel_report(samples)
            if n:
                print("")
                print("sentinel-zero samples: {} {}".format(n, detail))
        if report.failures:
            print("")
            print("failures ({}):".format(len(report.failures)))
            for sid, msg in report.failures[:20]:
                print("  {}: {}".format(sid, msg))

    return 0


def _to_rows(report):
    from .io_utils import results_to_rows
    return results_to_rows(report.results, conditions=report.conditions)


if __name__ == "__main__":
    sys.exit(main())
