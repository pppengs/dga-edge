# -*- coding: utf-8 -*-
"""scripts/fetch_datasets.py

Download the public DGA datasets into .cache/ and verify their SHA-256.

Why a script instead of the files themselves: none of the upstream dataset
repositories declares an open-source licence, so redistributing their data here
would be a licence violation. Fetching on demand and verifying a hash keeps the
experiments reproducible while respecting that.

Usage:
    python scripts/fetch_datasets.py            # fetch everything missing
    python scripts/fetch_datasets.py --check    # verify cache, download nothing
    python scripts/fetch_datasets.py --force    # re-download
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, ".cache")
MANIFEST = os.path.join(ROOT, "data", "manifest.json")


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def load_manifest():
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        return json.load(fh)


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    print("  downloading {}".format(url))
    with urllib.request.urlopen(url, timeout=60) as response, open(tmp, "wb") as fh:
        fh.write(response.read())
    os.replace(tmp, dest)


def verify(path, expected_sha, expected_bytes=None):
    if not os.path.exists(path):
        return False, "missing"
    actual = sha256_of(path)
    if actual != expected_sha:
        return False, "sha256 mismatch (got {}, expected {})".format(actual, expected_sha)
    if expected_bytes is not None and os.path.getsize(path) != expected_bytes:
        return False, "size mismatch"
    return True, "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify only, no downloads")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args()

    manifest = load_manifest()
    failures = 0

    print("cache directory: {}".format(CACHE))
    for dataset in manifest["datasets"]:
        print("")
        print("{} ({} samples, licence: {})".format(
            dataset["id"], dataset["samples"], dataset["license"]))
        for entry in dataset["files"]:
            dest = os.path.join(CACHE, entry["cache_as"])
            ok, why = verify(dest, entry["sha256"], entry["bytes"])
            if ok and not args.force:
                print("  {}: cached and verified".format(entry["cache_as"]))
                continue
            if args.check:
                print("  {}: {}".format(entry["cache_as"], why))
                failures += 1
                continue
            try:
                download(entry["url"], dest)
            except Exception as exc:
                print("  FAILED: {}".format(exc))
                failures += 1
                continue
            ok, why = verify(dest, entry["sha256"], entry["bytes"])
            print("  {}: {}".format(entry["cache_as"], why))
            if not ok:
                failures += 1

    print("")
    if failures:
        print("{} problem(s).".format(failures))
        print("If a download failed with an SSL error, retry - the upstream CDN")
        print("occasionally drops connections from scripted clients.")
        return 1
    print("all datasets present and verified.")
    print("NOTE: raw data is gitignored and must not be committed (no upstream licence).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
