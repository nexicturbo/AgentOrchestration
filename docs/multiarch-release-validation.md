# Multi-Arch Release Validation

Release automation must validate every architecture-specific image digest before
publishing a combined multi-arch manifest. A release is valid only when every
required architecture has:

- a digest in `sha256:<64 lowercase hex>` format,
- passing test status,
- passing security scan status,
- a matching source commit when `--expected-source-sha` is provided.

## Digest Input

The validation script accepts JSON or YAML:

```yaml
architectures:
  - architecture: linux/amd64
    image: ghcr.io/acme/agent-orchestrator
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    test_status: passed
    scan_status: success
    source_sha: $GITHUB_SHA
  - architecture: linux/arm64
    image: ghcr.io/acme/agent-orchestrator
    digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    test_status: passed
    scan_status: success
    source_sha: $GITHUB_SHA
```

## Release Gate

Run this step after per-architecture builds, tests, and scans, and before any
manifest push:

```bash
python .github/scripts/validate_multiarch_release.py \
  build/image-digests.yaml \
  --expected-source-sha "$GITHUB_SHA" \
  --output build/validated-multiarch-manifest.json
```

The command exits with status 2 when any architecture is missing, duplicated,
unexpected, stale, malformed, untested, or unscanned. On success it writes a
validated digest manifest containing only approved architecture digests.

## Release Summary

When `GITHUB_STEP_SUMMARY` is present, the script appends a table listing each
architecture, digest, test status, scan status, and source commit. This summary
is the release evidence that each image included in the combined manifest passed
the required architecture-specific gates.
