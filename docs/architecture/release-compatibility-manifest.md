# Release Compatibility Manifest

## 1. Purpose and authority

The Paper Data Suite release compatibility manifest is the suite shell's
machine-readable declaration of the exact PDS-owned release composition
qualified by one suite version.

The v1 resource is:

```text
paper_data_suite/data/release_compatibility_v1.json
```

The normative ownership contract remains
[`suite-shell-boundaries.md`](suite-shell-boundaries.md). This document refines
that contract for release qualification; it does not transfer authority over
Core or module-owned records, business rules, or workflows.

The central distinction is:

```text
package metadata compatibility
!=
suite-qualified release composition
```

A dependency such as:

```text
pds-core>=0.6,<0.7
```

describes package-level resolver compatibility. It does not prove that every
Core version in that range has been tested and accepted for a particular suite
release.

The manifest records the exact composition the suite has qualified.

## 2. Contract identity

The v1 manifest identifies itself with:

```text
record_type = paper_data_suite_release_compatibility_manifest
contract_version = 1
```

The contract version is independent of the suite package version.

Changing the supported component composition does not by itself require a
manifest contract-version change. A breaking change to the structure or meaning
of the manifest does.

The active manifest is bundled inside the `paper-data-suite` wheel and loaded
through installed-package resources. Loading does not depend on the current
working directory or a source checkout.

## 3. Suite identity

The `suite` object identifies the distribution that owns the declaration:

```text
distribution
version
release_status
```

For the current development package:

```text
distribution = paper-data-suite
version = 0.1.0.dev0
release_status = development
```

The manifest version must equal the package's authoritative
`paper_data_suite.__version__`.

The development manifest must not claim a final `0.1.0` release before the
release issue actually changes the package version and release status.

## 4. Python qualification

The `python` object records:

```text
specifier
tested_minors
```

The current suite qualification is:

```text
specifier = >=3.11,<3.15
tested_minors = 3.11, 3.12, 3.13, 3.14
```

This is deliberately narrower than unbounded package metadata such as
`>=3.11`.

A future Python 3.15 interpreter does not become suite-qualified merely because
the package installer accepts it. Qualification must be updated explicitly and
backed by the applicable suite validation.

## 5. Component rows

Every supported component row is an exact qualification record with these
semantic fields:

```text
component_id
display_name
purpose
repository
distribution
import_name
required
compatibility_status
version
requires_python
release
capabilities
entry_points
external_prerequisites
```

The active v1 manifest permits at most one supported version for a given
component ID and one row for a distribution.

A supported row means:

> this exact published component release is qualified by this exact suite
> manifest.

It does not mean that the component is installed on the current machine.

For rows declaring `launchable_application`, `purpose` is a short, bounded,
single-line teacher-facing description used by suite navigation. It is not a
domain-capability catalog and must not encode claims such as `can_grade`,
`can_group`, or `can_review`. Non-launchable rows use `null`.

The current `0.1.0.dev0` development contract incorporates this field into v1
before the first final v1 suite release. After a final v1 release exists,
structural changes must follow the contract-versioning rule above rather than
being added silently.

## 6. Required, optional, and runtime state

These dimensions are distinct:

```text
suite support
required/optional composition
runtime installation state
```

Core is required by the v0.1.0 suite shell.

Qualified sibling applications are optional. Their absence is therefore a valid
partial-installation state.

For example:

```text
ScoreForm 0.10.0
supported by the active suite
optional to install
currently absent
```

is valid.

Conversely:

```text
ScoreForm 0.11.0
installed
absent from the active manifest
```

must not be treated as supported merely because pip accepts its dependencies.

Runtime states such as `installed`, `missing`, `broken`, `shadowed`, or
`incompatible` are not static manifest statuses. Later bootstrap, doctor,
discovery, and acceptance issues compare the environment to this declaration.

## 7. Exact release artifacts

Every supported component row binds to one official published wheel through:

```text
repository
release tag
wheel filename
SHA-256 digest
```

The digest is lowercase hexadecimal and covers the exact release-asset bytes.

Release qualification must not be derived from:

- a locally rebuilt wheel;
- an editable checkout;
- a mutable branch;
- a source archive rebuilt locally;
- an unknown package cache;
- or a different artifact that happens to report the same version.

The current development manifest qualifies these exact component versions:

| Component | Distribution | Version | Required |
|---|---|---:|---|
| Core | `pds-core` | `0.6.0` | yes |
| Concord | `pds-concord` | `0.2.0` | no |
| Quillan | `quillan` | `0.9.0` | no |
| ScoreForm | `scoreform` | `0.10.0` | no |
| Vitrine | `pds-vitrine` | `0.2.0` | no |

The JSON manifest is the machine-readable source of truth for the exact wheel
filenames and SHA-256 digests. This document deliberately does not duplicate
those digests.

## 8. Published-release-only rule

A supported component must correspond to an immutable published GitHub Release
asset in the `Paper-Data-Suite` organization.

Mutable development state is not a supported release.

Accordingly:

- Meridian development source is not presently a supported manifest row;
- Portia has no executable application release and is not fabricated as one.

A future release can be added only by an explicit manifest change and renewed
artifact qualification.

No `latest` lookup, nearest-version selection, wildcard support, or semver-family
inference is permitted.

## 9. Entry points and capabilities

The suite architecture distinguishes application launching, Core routing, and
publication capabilities.

The manifest therefore represents these public entry-point groups separately:

```text
console_scripts
paper_data_suite.modules
paper_data_suite.publication_producers
```

A component may expose any valid subset.

This prevents false implications such as:

```text
routing module
=
launchable application
=
publication producer
```

Those identities are not equivalent in Paper Data Suite.

The bounded capability vocabulary describes only integration-relevant suite
facts, such as:

```text
shared_core
launchable_application
routing_module
publication_producer
publication_consumer
```

It does not create a domain-feature catalog such as `can_grade`, `can_group`, or
`can_review_behavior`.

Domain semantics remain owned by the corresponding module.

## 10. External prerequisites

`external_prerequisites` records non-Python software requirements that later
environment diagnostics may need to probe.

It does not duplicate ordinary wheel `Requires-Dist` metadata.

For example, PDF scan workflows in ScoreForm and Quillan require the external
`pdftoppm` command supplied by Poppler. The manifest may identify that command
and its purpose, but it does not contain package-manager recipes, installer
URLs, registry edits, or machine-mutating commands.

Issue #6 owns actual diagnostic probing. Issue #5 owns bootstrap and remediation
planning.

## 11. Not a package index or dependency lock

The manifest is not:

- PyPI;
- an alternate package index;
- a mirror list;
- a transitive Python dependency graph;
- a `requirements.txt`;
- a package solver;
- an installer;
- an update engine;
- a historical catalog of all PDS releases.

Python dependency metadata remains in the component wheels.

The active suite release records only the exact PDS-owned release identities and
bounded external prerequisites needed for suite qualification.

Historical suite releases preserve their own historical declarations through
their own released artifacts and source history.

## 12. Self-hash exclusion

The manifest does not contain the SHA-256 digest of the `paper-data-suite` wheel
that contains it.

Embedding the containing wheel's own digest would be self-referential:

```text
manifest gains suite-wheel digest
-> wheel bytes change
-> digest changes
-> manifest must change
-> wheel bytes change again
```

The bundled manifest authenticates subordinate PDS component artifacts.

Authentication of the suite wheel itself belongs to external release/bootstrap
metadata and the final release process.

## 13. Validation and trust model

The repository provides three complementary checks.

### 13.1 Manifest validation

```powershell
python .\scripts\validate_compatibility_manifest.py
```

This validates the v1 structure and suite invariants without inspecting the
current workspace or installed sibling applications.

### 13.2 Published artifact verification

```powershell
python .\scripts\verify_compatibility_artifacts.py `
  --artifact-dir <directory-containing-declared-wheels>
```

This verifies the declared wheels directly by exact:

- filename;
- SHA-256;
- distribution metadata;
- version metadata;
- `Requires-Python`;
- public entry-point groups, names, and targets.

The verifier does not install or import candidate component wheels.

### 13.3 Built-suite validation

```powershell
python .\scripts\check_package.py <suite-wheel>
python .\scripts\smoke_test_wheel.py <suite-wheel> <core-wheel>
```

The package checker proves that the compatibility resource is inside the built
suite wheel and agrees with the suite wheel's identity.

The clean installed-wheel smoke test proves that the manifest can be loaded
outside the source checkout, creates no working-directory artifacts, attempts no
network access, and does not import sibling PDS applications.

CI performs the same checks and separately authenticates the declared official
release assets.

## 14. Side-effect and privacy boundary

Loading the compatibility manifest must not:

- inspect a PDS workspace;
- read student or class data;
- enumerate installed sibling applications;
- import sibling application packages;
- make network requests;
- install software;
- write files;
- modify environment variables.

The manifest contains software release metadata only.

It contains no:

- workspace path;
- class ID;
- student ID;
- roster;
- school-year record;
- credential;
- token;
- machine identifier;
- domain record.

## 15. Updating qualification

A supported component version changes only through explicit suite work.

Updating a row requires:

1. selecting a specific published release;
2. authenticating the exact official wheel bytes;
3. recording the exact wheel filename and SHA-256;
4. validating wheel `Name`, `Version`, and `Requires-Python`;
5. validating expected public entry points;
6. running relevant suite integration qualification;
7. running repository tests, lint, typing, package checks, and CI;
8. reviewing the manifest diff.

The shell must never update the declaration merely because a newer component
release exists.

## 16. Relationship to later v0.1.0 work

This issue establishes compatibility data and verification only.

Later issues consume it:

- #5 — verified Windows bootstrap and update planning;
- #6 — `pds doctor`;
- #7 — installed-module discovery and launching;
- #13 — combined installed-suite acceptance;
- #14 — final security, privacy, usability, and release audit.

Those issues may classify an actual environment, propose explicit remediation,
or launch supported components. They must not weaken the fail-closed release
qualification established here.
