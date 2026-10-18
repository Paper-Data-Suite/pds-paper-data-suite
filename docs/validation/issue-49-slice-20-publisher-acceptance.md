# Issue #49 — Slice 20 validation and acceptance

- **Scope:** `evergreen_publisher_acceptance.py`, its focused test, this
  validation note and the architecture note. No preexisting production files
  changed; no existing CLI flags added.
- **Read-only:** The wrapper reads the journal/wheelhouse, re-verifies
  independently signed release documents and conditionally invokes existing
  opt-in public-console checks. It does not persist a receipt, invoke package
  installation or touch classroom records.
- **Positive test:** a synthetic root-signed registry independently delegates
  a test module release key, matching a signed dependency lock and exact
  prepared stage. With a subprocess stub, the wrapper observes one importable
  root console while preserving all installed stage bytes and the journal.
- **Negative tests:** missing/malformed publisher envelopes, a cross-publisher
  signature, valid signature for a substituted digest, changed locked wheel,
  stage-source tampering, stale journal phase, incorrect journal evidence,
  console entry point mismatch and post-import provenance disagreement all
  fail closed. Rejected publisher evidence never spawns the subprocess probe.
- **Fixture keys:** test-only and synthetic; never provisioning authority.
- **Local gate:** 512 tests passed across issue #49 Slices 1–20 on Linux.
- **Required Windows gate:** Ruff import sorting, `ruff format`, lint,
  `mypy --strict`, all focused issue #49 tests and `pip check` before commit.
  Unprivileged symlink tests may skip on Windows, as in earlier slices.
- **Security posture:** An observation does not authorize launch or activate
  software. Real release signing, external Core provenance, Windows native
  templates and durable state continuity remain open.
