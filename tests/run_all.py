#!/usr/bin/env python3
"""Run all test_*.py files in the tests/ directory.

Discovers test modules, runs each, and reports totals.
"""
import os
import subprocess
import sys
from pathlib import Path


def main():
    tests_dir = Path(__file__).parent
    test_files = sorted(tests_dir.glob("test_*.py"))

    if not test_files:
        print("No test files found.")
        sys.exit(1)

    total_passed = 0
    total_failed = 0
    results = []

    for tf in test_files:
        print(f"\n{'=' * 60}")
        print(f"Running {tf.name}")
        print('=' * 60)

        proc = subprocess.run(
            [sys.executable, str(tf)],
            cwd=str(tests_dir.parent),
        )

        if proc.returncode == 0:
            results.append((tf.name, "PASS"))
        else:
            results.append((tf.name, "FAIL"))

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print('=' * 60)
    for name, status in results:
        icon = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{icon}] {name}")

    passed = sum(1 for _, s in results if s == "PASS")
    failed = sum(1 for _, s in results if s == "FAIL")
    print(f"\n{passed} files passed, {failed} files failed (out of {len(results)} total)")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
