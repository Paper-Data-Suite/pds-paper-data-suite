# Security Policy

## Project status

`pds-paper-data-suite` is in pre-release development. There is currently no
supported suite-shell release.

The repository is intended to become a local-first orchestration layer for
Paper Data Suite. Local-first operation does not remove the need for appropriate
filesystem access controls, backups, retention practices, authorization, and
compliance with applicable school, district, state, and federal requirements.

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

Use GitHub Issues for non-sensitive security, privacy, integrity, or data-safety
concerns.

Do not include real student data, private school or district information,
credentials, production workspace contents, or other sensitive material in a
public issue. If sensitive details are required to investigate a concern,
describe the problem publicly only at a non-sensitive level and request a
private follow-up channel.

## Scope and ownership

This repository must not become an alternate authority for records owned by PDS
Core or another PDS module. Security-sensitive orchestration must preserve the
ownership, validation, path-safety, provenance, and authorization boundaries of
the public services it composes.

Exact suite-shell ownership and integration rules are established through the
v0.1.0 architecture work and should be treated as authoritative once accepted.

## Supported versions

There is no supported release yet.

| Version | Status |
| --- | --- |
| `main` | Development only |
| Released versions | None |

Security and maintenance support policy for released suite versions will be
defined before the first public release.
