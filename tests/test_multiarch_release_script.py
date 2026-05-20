import os
import subprocess
import sys


SCRIPT = ".github/scripts/validate_multiarch_release.py"
AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def test_script_writes_validated_manifest_and_step_summary(tmp_path):
    input_path = tmp_path / "digests.yaml"
    output_path = tmp_path / "validated.json"
    summary_path = tmp_path / "summary.md"
    input_path.write_text(
        f"""
architectures:
  - architecture: linux/amd64
    image: ghcr.io/acme/agent
    digest: {AMD64}
    test_status: passed
    scan_status: success
    source_sha: release-sha
  - architecture: linux/arm64
    image: ghcr.io/acme/agent
    digest: {ARM64}
    test_status: passed
    scan_status: success
    source_sha: release-sha
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["GITHUB_STEP_SUMMARY"] = str(summary_path)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            str(input_path),
            "--expected-source-sha",
            "release-sha",
            "--output",
            str(output_path),
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output_path.exists()
    assert "linux/amd64" in output_path.read_text(encoding="utf-8")
    summary = summary_path.read_text(encoding="utf-8")
    assert "Multi-arch image validation" in summary
    assert "linux/arm64" in summary
    assert "release-sha" in summary


def test_script_fails_before_output_for_missing_architecture_scan(tmp_path):
    input_path = tmp_path / "digests.yaml"
    output_path = tmp_path / "validated.json"
    input_path.write_text(
        f"""
architectures:
  - architecture: linux/amd64
    image: ghcr.io/acme/agent
    digest: {AMD64}
    test_status: passed
    scan_status: success
  - architecture: linux/arm64
    image: ghcr.io/acme/agent
    digest: {ARM64}
    test_status: passed
    scan_status: failed
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            str(input_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert not output_path.exists()
    assert "linux/arm64 is missing passing scan status" in result.stderr
