# Issue #49 Slice 31 acceptance

Base branch: `49-evergreen-launch-and-supported-composition-upgrades`
Exact parent commit: `65115b3a5295f2cf13f03c9e05837f442eca6ca1`

## Acceptance coverage

- Explicit opt-in and bounded timeout; no subprocess for absent optional provider.
- Signed module identity, exact installed pip/native evidence and before/after drift checks.
- Installed Core publisher/Publication Record schema module ownership and exact file origins.
- Core structural producer-profile validator, module identity and schema support.
- Genuine offline-pip negative fixture: an authenticated and importable declaration cannot qualify when staged Core is absent.
- No reader, compatibility evaluation, publication callback, classroom workspace access, or active installation mutation.

Local validation: 18 Slice 31 tests and 89 affected Slice 27–31 tests passed on Linux. A wider local run exceeded its execution limit; the packaged Windows runner is responsible for the full Slice 1–31 gate.

This slice is additive and does not change `pds launch`.
