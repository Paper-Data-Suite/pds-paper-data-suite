# Issue #49 — Slice 27: authenticated public provider declarations

**Scope:** Additive, read-only Core/module provider discovery evidence; no production wiring.

## Supported public Core entry-point groups

The known, documented interoperability discovery namespaces include
`paper_data_suite.modules` (PDS2 routing),
`paper_data_suite.module_operations` (readiness/attention), and
`paper_data_suite.publication_producers` (publication compatibility).
Public reader consumption and every other integration capability are separate
contracts; an installed declaration cannot confer their qualification.

`inspect_authenticated_provider_declaration` begins with a complete
publisher-authenticated real-pip installed-file audit. It binds the selected
component to the independently root-signed registry and the exact locked
publisher-approved wheel, independently rehashes its wheel around metadata
inspection, and checks the corresponding installed entry-point metadata.
The signed wheel must own the Python source module named as provider target;
entry-point name must equal the registered component ID. Metadata is parsed
strictly and does not cause Python imports or provider calls. A final complete
publisher/pip audit detects normal intervening installed-file drift.

Return values are `DECLARED_NOT_TESTED` and `NOT_DECLARED`. A missing provider
is a per-capability limitation, **not a reason to prohibit a valid module
launcher**. A present provider has not been invoked, its result has not been
validated by Core, and it has not passed versioned contract acceptance.
This API cannot issue active receipts, advertise integration authorization,
or authorize code execution.

## Deferred qualification

The check is metadata-only and independent of integration attestations. Real
provider readiness requires an explicitly consented, bounded isolated runtime
probe, application-specific provider result verification, matching Core public
contract versions, and robust post-probe software integrity checks. A subprocess
is not a security sandbox. Exact mixed-module integration qualifications remain
separate from launchability. The signed release channel, interpreter/provenance,
protected installation continuity, migration and rollback remain prerequisites
for production activation.
