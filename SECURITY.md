# Security Policy

## Project status

`pds-paper-data-suite` is preparing its first public teacher-pilot release.

The source identity is promoted to `0.1.0` for final release qualification;
no supported public `paper-data-suite` release exists until the audit is
complete and the maintainer explicitly publishes the release.

Paper Data Suite is local-first. Local-first operation does not remove the need
for appropriate filesystem access controls, backups, retention practices,
authorization, and compliance with applicable school, district, state, and
federal requirements.

## Student data and privacy

Do not commit, upload, or publicly post:

- real student data or identifiers;
- real class rosters;
- scanned or photographed student work;
- grades, scores, standards ratings, or feedback tied to real students;
- behavior, intervention, support, communication, or portfolio records tied to
  real students;
- production Paper Data Suite workspaces or backups;
- private school or district documents;
- credentials, access tokens, secrets, or private configuration; or
- diagnostic bundles containing sensitive classroom information.

Repository examples, fixtures, screenshots, demonstrations, and tests must use
synthetic data.

A Paper Data Suite workspace may contain sensitive educational records owned by
PDS Core and installed modules. Do not place a real classroom workspace inside
this source repository.

## Reporting a concern

Use GitHub Issues only for non-sensitive security, privacy, integrity, or
data-safety concerns.

Do not include real student data, private school or district information,
credentials, production workspace contents, exploit details that should remain
private, or other sensitive material in a public issue.

GitHub Private Vulnerability Reporting was maintainer-confirmed enabled before
release identity promotion on August 25, 2026. Use the repository's private
**Report a vulnerability** workflow for sensitive vulnerability reports.

If Private Vulnerability Reporting is unexpectedly unavailable, do not disclose
sensitive details in a public issue. Open only a non-sensitive issue stating
that a private security-reporting channel is needed.

## Support policy

Paper Data Suite v0.1.x is an early teacher-pilot series, not an LTS line.

Once v0.1.0 is published:

- only the latest released `0.1.x` version is supported;
- `main` remains development-only and is not a supported release;
- when a newer `0.1.x` release supersedes an older one, the older pilot release
  becomes unsupported;
- there is no guaranteed vulnerability-response SLA, maintenance window, or
  backport period;
- fixes may require upgrading to the latest pilot release.

Until v0.1.0 is actually published, the supported-release table remains:

| Version | Status |
| --- | --- |
| `main` | Development only |
| `0.1.0` | Final release qualification; not supported until published |
| Released versions | None yet |

## Scope and ownership

This repository must not become an alternate authority for records owned by PDS
Core or another PDS module. Security-sensitive orchestration must preserve the
ownership, validation, path-safety, provenance, and authorization boundaries of
the public services it composes.

The normative ownership and integration contract is
[`docs/architecture/suite-shell-boundaries.md`](docs/architecture/suite-shell-boundaries.md).
