#!/usr/bin/env python3
"""Validate multi-architecture digests before manifest publication."""

# flake8: noqa: E402

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.common.multiarch_release import (
    DEFAULT_REQUIRED_ARCHITECTURES,
    MultiArchReleaseError,
    load_architecture_records,
    validate_multiarch_release,
    write_validated_manifest,
)  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate per-architecture image digests before publish",
    )
    parser.add_argument(
        "input",
        help="JSON/YAML file with architecture digests",
    )
    parser.add_argument(
        "--required-arch",
        action="append",
        dest="required_architectures",
        default=[],
        help="Required architecture, for example linux/amd64",
    )
    parser.add_argument(
        "--expected-source-sha",
        help="Release commit SHA every architecture must come from",
    )
    parser.add_argument(
        "--output",
        default="validated-multiarch-manifest.json",
        help="Path for the validated digest manifest",
    )
    args = parser.parse_args()

    required = args.required_architectures or DEFAULT_REQUIRED_ARCHITECTURES
    try:
        manifest = validate_multiarch_release(
            load_architecture_records(args.input),
            required_architectures=required,
            expected_source_sha=args.expected_source_sha,
        )
    except MultiArchReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    write_validated_manifest(manifest, args.output)
    summary = manifest.render_summary()
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write("## Multi-arch image validation\n\n")
            summary_file.write(summary)
            summary_file.write("\n")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
