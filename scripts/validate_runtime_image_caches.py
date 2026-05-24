"""Validate runtime Docker image cache hygiene."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


REQUIRED_RUNTIME_CLEANUPS = (
    "/root/.cache",
    "/var/cache/apt",
    "/var/lib/apt/lists",
    "/tmp/wheels",
)

FORBIDDEN_RUNTIME_INSTALL_PATTERNS = (
    re.compile(r"\bapt-get\s+update\b"),
    re.compile(r"\bapt-get\s+install\b"),
    re.compile(r"\bapk\s+add\b"),
    re.compile(r"\bpip\s+install\b(?![^\n]*--no-cache-dir)"),
    re.compile(r"\bpython\s+-m\s+pip\s+install\b(?![^\n]*--no-cache-dir)"),
)


def _logical_lines(text: str) -> List[str]:
    lines: List[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line and not pending:
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        lines.append((pending + line).strip())
        pending = ""
    if pending:
        lines.append(pending.strip())
    return lines


def _runtime_stage(lines: Sequence[str]) -> List[str]:
    stage_start = None
    for index, line in enumerate(lines):
        if re.match(r"FROM\s+\S+\s+AS\s+runtime\b", line, re.IGNORECASE):
            stage_start = index
            break
    if stage_start is None:
        raise ValueError("Dockerfile must define a final stage named runtime")

    stage = []
    for line in lines[stage_start + 1:]:
        if line.upper().startswith("FROM "):
            break
        stage.append(line)
    return stage


def validate_dockerfile(path: Path) -> List[str]:
    lines = _logical_lines(path.read_text())
    runtime_lines = _runtime_stage(lines)
    runtime_text = "\n".join(runtime_lines)
    errors: List[str] = []

    for cleanup_path in REQUIRED_RUNTIME_CLEANUPS:
        if cleanup_path not in runtime_text:
            errors.append(f"runtime stage does not remove {cleanup_path}")

    for line in runtime_lines:
        if not line.upper().startswith("RUN "):
            continue
        for pattern in FORBIDDEN_RUNTIME_INSTALL_PATTERNS:
            if pattern.search(line):
                errors.append(
                    "runtime package install must be local/no-cache: "
                    f"{line}"
                )

    if "COPY --from=builder" not in runtime_text:
        errors.append("runtime stage must copy artifacts from builder stage")
    if "COPY . " in runtime_text or "COPY ./" in runtime_text:
        errors.append("runtime stage must not copy the whole build context")

    return errors


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dockerfile", default="Dockerfile")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = Path(args.dockerfile)
    errors = validate_dockerfile(path)
    if errors:
        for error in errors:
            print(f"runtime image cache policy failed: {error}")
        return 1

    print("runtime image cache policy passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
