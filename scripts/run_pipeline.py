"""CLI entry point: run the Hanoi OT data pipeline.

Usage:
    python scripts/run_pipeline.py            # full real-data pipeline
    python scripts/run_pipeline.py --synthetic  # tiny synthetic fixture
    python scripts/run_pipeline.py --force-download
"""

from __future__ import annotations

import argparse
import json
import sys

from hanoi_ot.config import setup_logging
from hanoi_ot.pipeline import PipelineError, run, run_synthetic


def main(argv: list[str] | None = None) -> int:
    """Parse args and execute the requested pipeline mode.

    Args:
        argv: CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 success, 1 failure).
    """
    parser = argparse.ArgumentParser(description="Hanoi OT data pipeline")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Run against the tiny synthetic fixture instead of real data.",
    )
    parser.add_argument(
        "--force-download", action="store_true",
        help="Re-download raw sources even if already present.",
    )
    args = parser.parse_args(argv)
    setup_logging()
    try:
        if args.synthetic:
            summary = run_synthetic()
        else:
            summary = run(force_download=args.force_download)
    except PipelineError as e:
        print(f"PIPELINE FAILED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
