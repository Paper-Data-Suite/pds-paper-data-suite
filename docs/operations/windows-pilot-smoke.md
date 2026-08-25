# Windows v0.1.0 Pilot Smoke

`run_windows_pilot_smoke.py` is the synthetic Windows acceptance runner
for final Paper Data Suite v0.1.0 release qualification.

It is intentionally separate from ordinary CI. The release claim is
Windows-first, so the final candidate must also run on a real maintainer Windows
machine rather than relying only on GitHub-hosted Windows runners.

## Safety boundary

The runner does not use a real classroom workspace.

It creates temporary:

- artifact directories;
- candidate distributions;
- managed bootstrap environment;
- user configuration directories;
- synthetic workspaces;
- backup/restore locations; and
- installed-wheel smoke environments.

`PYTHONPATH` and any inherited `PDS_WORKSPACE_ROOT` are removed from isolated
command environments. User-profile/config paths used by the managed smoke are
redirected beneath the temporary pilot root.

The machine's real `PATH` remains available so the pilot can prove that the
teacher machine actually exposes `pdftoppm`/Poppler. The runner executes
`pdftoppm -v`; this proves real command execution, not printer/scanner hardware
operation.

## What the runner proves

The runner:

1. downloads exact PDS component wheels from the bundled compatibility contract;
2. downloads the exact qualified pip wheel from `release_tooling_v1`;
3. verifies declared SHA-256 identities;
4. builds the current suite candidate;
5. runs `twine check` and `scripts/check_package.py`;
6. authenticates the complete release-artifact set;
7. runs the real Windows bootstrap into a temporary managed environment;
8. runs installed `pip check`, `pds --version`, workspace setup, `pds doctor`,
   and `pds modules`;
9. executes the host `pdftoppm`;
10. runs repository-owned installed-wheel acceptance for:
    - base CLI/import behavior;
    - workspace workflows;
    - shared classroom setup;
    - backup creation;
    - restore;
    - suite settings;
    - application inventory and launch/quit; and
    - combined suite interoperability.

A PASS prints a JSON evidence record ending in:

```text
WINDOWS PILOT SMOKE: PASS
```

## Release boundary

The runner now requires the promoted identity `0.1.0` and is reused for
post-promotion final Windows qualification. The historical evidence below
records the earlier `0.1.0.dev0` pre-promotion run unchanged.

A successful Windows smoke is necessary but not sufficient for publication.
Final artifact validation, the post-promotion `release-gate`, and explicit
maintainer authorization remain separate gates.

## Real Windows pilot evidence

The final pre-promotion synthetic Windows teacher-pilot smoke passed on
2026-08-24 with:

- platform: `win32`;
- Python: `3.11.9`;
- candidate suite identity: `0.1.0.dev0`;
- candidate wheel:
  `paper_data_suite-0.1.0.dev0-py3-none-any.whl`;
- pilot-run candidate wheel SHA-256:
  `f83e15780d2a5e704f188536587fa4793612df4e18193b0642a6215185cef198`;
- exact Core wheel: `pds_core-0.6.3-py3-none-any.whl`;
- managed bootstrap: PASS;
- managed doctor: PASS;
- qualified application composition: PASS;
- real host Poppler command:
  `pdftoppm version 25.07.0`;
- real host `pdftoppm` executable discovered under the installed WinGet Poppler
  package.

Installed workflow acceptance passed for:

1. base installed wheel;
2. workspace workflow;
3. shared classroom setup;
4. workspace backup;
5. workspace restore;
6. suite settings;
7. application inventory and launch; and
8. combined installed suite.

The run ended with `WINDOWS PILOT SMOKE: PASS`.

The SHA-256 above identifies the exact wheel exercised during the pilot. It is
**not** the final release artifact digest: later audit/documentation changes
alter the candidate wheel, and final wheel/sdist hashes are recorded only after
the release identity is promoted and the final tree is frozen.
