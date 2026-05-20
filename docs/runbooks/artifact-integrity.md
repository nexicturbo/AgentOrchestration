# Artifact Integrity Alert Runbook

## Trigger

`artifact_integrity_mismatch` fires when an artifact manifest declares a SHA-256
digest that does not match the downloaded blob bytes.

## Immediate Response

1. Treat the artifact as corrupted or tampered until proven otherwise.
2. Keep the quarantined blob for investigation. Do not restore it to the cache.
3. Check the blocked marker for the artifact id, expected digest, and actual digest.
4. Re-download the artifact from a trusted upstream source and verify its digest.
5. If the trusted source now produces a different digest, rotate the manifest and audit
   all consumers that read the previous blob.

## Recovery

1. Delete the blocked marker only after a trusted replacement blob has been verified.
2. Repopulate the cache with the verified blob.
3. Re-run the workflow that consumed the artifact.
4. If more than one artifact fails integrity checks, pause artifact reads and inspect
   storage replication, object-store lifecycle rules, and recent deploys.

## Escalation

Escalate to the storage on-call when:

- the same artifact id fails twice,
- multiple artifacts fail within a single rollout window,
- the actual digest matches another known artifact, or
- upstream cannot reproduce the expected digest.
