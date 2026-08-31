# Public Shadow evaluations

This directory is the public, redacted projection of the private Quantskills evaluation control plane.

- `current-scores.json` contains one current score for each of the 218 evaluated assets. Later immutable publications supersede earlier rows only for the same asset.
- `publications/*.jsonl` preserves all 224 historical score observations by source publication.
- `recommended.snapshot.json` is a Shadow-only, category-relative view. It does not change Registry listing and is not an investment endorsement.
- `manifest.json` hashes every public file and records the unchanged source score, attestation, and signed-envelope roots for each publication.

Each score row references the original signed attestation by key ID, payload digest, attestation key, and signed-envelope hash. Full signed payloads, model traces, candidate code, private security findings, and credentials remain private.

Verify the checked-in projection with:

```bash
python scripts/verify_public_evaluations.py
```

Maintainers regenerate it locally from the private publication roots with `scripts/export_public_evaluations.py`. CI never reads the private databases. After a change reaches `main`, GitHub Actions creates an OIDC-backed build-provenance attestation for the packaged public evaluation directory.
