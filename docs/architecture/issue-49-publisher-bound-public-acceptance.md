# Issue #49 — Slice 20: Publisher-bound public console acceptance

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `be37c23` (full hash enforced by runner)
**Status:** Additive, opt-in candidate acceptance. No live runtime wiring.

## Requirement

Slice 18's public-console import observation re-verifies a **root-signed closed
wheelhouse**, staged source inventory, interpreter/native executable evidence,
and pending journal state. That lock cannot replace the distinct **per-module
publisher-delegated release approval** supplied by Slice 19. Candidate code
must not be probed through the new publisher-bound path if a selected PDS
module release lacks independently authorized exact-wheel metadata.

`accept_publisher_bound_candidate_public_contracts` joins these checks:

1. Validate strictly bounded signed module envelope inputs and the exact
   candidate-verified journal identity. Require journal hashes for prepared
   record, registry, lock and native evidence to match the bytes presented.
2. Resolve a wheelhouse within the dedicated software root, outside the
   classroom workspace; reject unsafe and missing path ancestry.
3. Run Slice 19 `verify_publisher_bound_composition` using the independent
   root registry and delegated PDS publisher signatures. Every registered
   PDS distribution in the full lock, including transitive PDS dependencies,
   must be signed by its authorized publisher. This check precedes any import.
4. Invoke Slice 18's explicit public-console smoke, whose journal and
   selection locks span the import probes. It independently checks installed
   source and executable hashes before and after each set of probes and
   verifies the journal has not been changed during import.
5. Reauthenticate publisher evidence and compare exact signed release
   identities. Ensure the root console names, owners and callable target
   strings match those published in the exact signed wheel metadata.
6. Return an immutable **ephemeral observation**, including all PDS publisher
   payload hashes and an explicit list of nonregistered external dependencies.

Neither the root lock nor an unverified journal field may establish PDS
publisher authority. Direct calls to the older Slice 18 observation remain
available for testing but **are not sufficient evidence** for production
activation. Future integration code must call the publisher-bound entry point
and reject partially qualified stages.

## Important limitations

- This is not a runtime security sandbox. Importing an approved module executes
  its initialization code with the current OS user's permissions; invoking this
  acceptance step must always be explicit and subject to separate authorization.
- Publisher signatures do not authenticate **external dependencies** such as
  `pds-core` when not independently registered; the result reports their
  names rather than declaring them trusted releases. Separate Core provenance
  and capability checks are required before a production activation decision.
- The fixture uses synthetic private signing keys exclusively in test code.
  **No production signing keys or provisioned release feed** are included.
- The result provides no `can_launch`, activation or integration-qualification
  field. Locally writable journals/checkpoints cannot prove historical active
  state. Repeated reads and filesystem path checks are not a durable response
  to malicious same-user concurrency, hardlink substitution or OS compromise.
- This slice neither installs wheels nor selects or activates a staged slot,
  updates Suite's historical release manifest, touches PDS classroom files,
  runs in ordinary `pds launch`, nor makes network calls.

## Next steps

Review the real pip-created Windows ARM64/x64 environments (including pip's
`.data` installation layout and signed reproducible native launcher provenance),
Core/module public provider contract checks, protected installed-state
continuity, and explicit teacher-approved activation and rollback.
