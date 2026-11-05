# Suite #49 Slice 145 — normal module and launcher wiring

This implementation connects Slice 144's approved, read-only local package
assessment to the existing `pds modules` and `pds launch <module>` paths.
The historical `release_compatibility_v1.json` is **unchanged**. The optional
signed-catalog lab/diagnostic paths and all earlier update infrastructure are
also unchanged. Core itself remains a shared prerequisite, not a Suite app.

## Runtime policy

- List exactly the six approved applications: ScoreForm, Quillan, Concord,
  Meridian, Vitrine, and Portia. No arbitrary entry-point discovery becomes a
  launch permission or an added module.
- Use real distribution metadata in the active Python interpreter. Respect
  declared Python and dependency requirements, compatible Core ranges,
  bounded metadata, noneditable wheel metadata, and unique approved script
  ownership/target. A missing or incompatible app does not disable the rest.
- Resolve the script in the running interpreter's scripts directory using
  existing Suite launcher confinement; retain the established foreground
  subprocess environment sanitization and return-code/Recent Work behavior.
- Treat a matching historical version as **historical version evidence only**,
  never proof of official wheel provenance or complete mixed-module acceptance.
  Local metadata cannot independently authenticate an official wheel. Show the
  caution in module listing and on successful preflight before launch.
- Do not gate a valid module launcher on unrelated optional provider imports.
  Individual routing/publication/operations integrations remain separately
  qualified through their public contracts.

## Intentional limits

`pds doctor`, guided `pds setup`, historical installed-composition bootstrap,
and their old exact-version diagnostic tests are not changed by this slice;
Slice 146 owns the doctor/setup migration. No package is downloaded, installed,
downgraded, or removed. No classroom workspace or backup is opened.

## Qualification

Run targeted Slice 144/145 tests, the existing application/launch CLI tests,
Ruff over changed Python files, and mypy over the new adapter. Final installed
wheel exercises remain a Slice 147 acceptance gate.
