# Issue #49 — Slice 42 Windows validation

## Baseline and scope

Run `run_slice42.ps1 -Repo .` against the exact committed and pushed Slice 41 SHA `76cc835` on `49-evergreen-launch-and-supported-composition-upgrades`. This bundle adds four files: one production protocol module, one adversarial test module, architecture notes, and this validation record. It must not modify existing teacher launching, witness HTTP routes, checkpoint-store source, or classroom data.

The runner checks Git origin, branch, exact local and remote HEAD, clean tracked/staged/untracked state, absence of destination paths, exact SHA-256 payload hashes, Ruff import sorting and formatting, Ruff lint, strict mypy for the new production source, all Slice 1–42 issue tests, `pip check`, Git staged scope and whitespace, and finally commits/pushes only if every gate passes. This is a source-validation runner, not a witness writer. The actual Windows pass/skip totals are recorded after execution, not asserted here.

## Security regression cases

The test module covers canonical request generation and parsing; signed prior/successor readbacks; explicitly approved service CAS; CAS replay refusal; denied/failed independent authorization; wrong service context; wrong key/revision/witness/offline failure; prior-head ambiguity; signed successor observation after lost acknowledgment; competing successor races; alien post-CAS signed heads; malformed/duplicated/oversized/modified request fields; and no subprocess/teacher-launch effects. Test service credentials, SQLite and approval callbacks are mocks of independently administered deployment; they **do not demonstrate actual independent administration or protected physical Windows installation**.

## Mandatory boundary before production

The service-side adapter cannot be called from a teacher-local Suite process and must not be exposed through the existing head-read-only endpoint. Future work must provide a reviewed authenticated write service, protected activation attestation and consent, durable local receipt commit, forward reconciliation after an ambiguous witness advance, and physical end-to-end acceptance. No production activation claim should be made for Slice 42.
