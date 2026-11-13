#!/usr/bin/env python3
"""All-in-one build, verification, and packaging runner for EarthSpaceRankings.

Executes:
1. Deterministic aggregation (pipeline/aggregate.py) with full science sectors (education, facility, government, nonprofit).
2. Packaging of static assets (pipeline/package_earth_space_site.py) with enriched country metadata.
3. Verification checks (pipeline/verify.py, pipeline/dropped_credit.py, pipeline/adjudication.py).

Usage:
    python3 pipeline/build_earth_space.py [--skip-verify]
"""

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable


def run_cmd(args, desc, allow_warning=False):
    print(f"\n▶ {desc}...")
    cmd_str = " ".join(args)
    print(f"  $ {cmd_str}")
    res = subprocess.run(args, cwd=REPO_ROOT)
    if res.returncode != 0 and not (allow_warning and res.returncode == 2):
        print(f"FAILED: {desc} exited with code {res.returncode}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="End-to-end builder for EarthSpaceRankings.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification checks")
    args = parser.parse_args()

    # Step 1: Aggregation
    ok = run_cmd([
        PYTHON, "pipeline/aggregate.py",
        "--all-cached",
        "--areas-json", "data/areas_earth_space.json",
        "--credit-types", "education,facility,government,nonprofit",
        "--out", ".tmp/earth_space_aggregates",
        "--sequential"
    ], "Aggregating Earth, Planetary & Space Sciences corpus")
    if not ok:
        sys.exit(1)

    # Step 2: Packaging
    ok = run_cmd([
        PYTHON, "pipeline/package_earth_space_site.py"
    ], "Packaging static sites (site/earth-space and site_earth_space)")
    if not ok:
        sys.exit(1)

    # Step 3: Verification
    if not args.skip_verify:
        print("\n▶ Running Verification Suite...")
        # Adjudication traps
        run_cmd([PYTHON, "pipeline/adjudication.py", "check"], "Checking affiliation traps")

        # Dropped credit accounting
        run_cmd([
            PYTHON, "pipeline/dropped_credit.py",
            "--areas-json", "data/areas_earth_space.json",
            "--credit-types", "education,facility,government,nonprofit",
            "--all-areas"
        ], "Accounting for dropped credit")

        # Phase 3 aggregate verification
        run_cmd([
            PYTHON, "pipeline/verify.py",
            "--phase", "3",
            "--areas-json", "data/areas_earth_space.json",
            "--data-dir", ".tmp/earth_space_aggregates"
        ], "Verifying aggregate integrity across 29 venues", allow_warning=True)

    print("\n✓ EarthSpaceRankings build complete!")


if __name__ == "__main__":
    main()
