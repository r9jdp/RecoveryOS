"""CLI for regenerating the checked-in RecoveryBench artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from .training import ARTIFACT_VERSION, DEFAULT_CASE_COUNT, DEFAULT_SEED, train_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "artifacts" / ARTIFACT_VERSION,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--case-count", type=int, default=DEFAULT_CASE_COUNT)
    args = parser.parse_args()
    report = train_artifact(args.output, seed=args.seed, case_count=args.case_count)
    print(
        f"wrote {report['report_version']} with "
        f"{report['dataset']['evaluation_case_count']} evaluation cases"
    )


if __name__ == "__main__":
    main()
