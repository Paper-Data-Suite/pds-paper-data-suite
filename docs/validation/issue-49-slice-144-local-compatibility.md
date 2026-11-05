# Suite #49 — Slice 144: approved local registry and compatibility observations

**Target branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Required parent:** `75f92a904a1dd1cc366168037cec6ac1420e04da` (Slice 143)
**Scope:** read-only inspection groundwork for the **streamlined** #49, not the original signing/update transaction.

## Delivered

- `paper_data_suite/evergreen_local_registry.py` defines seven audited component identities (Core plus ScoreForm, Quillan, Concord, Meridian, Vitrine, and Portia), including their approved console-script names and targets. Core is a dependency, not a Suite launchable application.
- `paper_data_suite/evergreen_local_compatibility.py` separates **local metadata compatibility**, **historical version-only comparison**, and **unverified origin**. An exact historical version does **not** authenticate installed bytes. Local compatibility does **not** certify cross-module operation or authorize process launch.
- Only the active interpreter's installed-distribution metadata is observed. Checks include installed identity and duplicate distribution names, `Requires-Python`, applicable direct and transitive `Requires-Dist` (including requested extras), Suite's declared Core requirement `>=0.6.3,<0.7`, editable installs, wheel metadata presence, active-environment confinement, approved entry-point owner/target, and duplicate/shadowed scripts. There are no GitHub calls, module imports, installation steps, administrator requirements, or workspace writes.
- Reuse the branch’s **existing** `packaging>=24,<27` runtime dependency; no dependency change or historical manifest edit is necessary.
- Targeted synthetic tests cover newer-than-historical Quillan, representative additional modules/Core, and negative metadata/dependency/ownership outcomes.

## Deliberate boundaries

1. The v0.1.0 `paper_data_suite/data/release_compatibility_v1.json` file is **not modified**. Its version values remain historical observations, not live acceptance caps.
2. All metadata-based observations report `PROVENANCE_UNVERIFIED`. Neither a matching version nor a wheel RECORD establishes publisher authenticity. The teacher must obtain manual wheels from the intended official release source; this local layer does not impersonate a trusted catalog.
3. `locally_compatible` describes metadata checks **only**. It is not a launcher permission. Slice 145 must reuse the existing safe `resolve_current_environment_launcher` and foreground dispatch; no new automatic update mechanism or privileged service is introduced.
4. `pds modules`, `pds launch`, `pds doctor`, and classroom `pds setup` are intentionally unchanged here. Slice 145/146 connect the new assessments to normal commands. Existing historical bootstrap paths are retained.
5. No arbitrary module IDs or console targets are supplied by untrusted installed packages. The approved registry is explicit and immutable. Changes to official console contracts require reviewed source changes.
6. Local checks do not verify the actual provenance, exact wheel contents, or whether optional producer-specific integration APIs are usable. Those are separate evidence/eligibility dimensions.

## Targeted qualification

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_issue49_slice144_local_compatibility.py
& .\.venv\Scripts\python.exe -m ruff check paper_data_suite/evergreen_local_registry.py paper_data_suite/evergreen_local_compatibility.py tests/test_issue49_slice144_local_compatibility.py
& .\.venv\Scripts\python.exe -m mypy paper_data_suite/evergreen_local_registry.py paper_data_suite/evergreen_local_compatibility.py
```

Passes above qualify *this slice*, not the #49 installed-wheel acceptance gate. Full suite/physical tests remain reserved for integration and release boundaries. If the project virtual environment lacks `packaging`, `pytest`, `ruff`, or `mypy`, restore the repo's declared development dependencies explicitly rather than letting this runner install anything silently.

## Next slice

**145:** adapt normal application inventory and `pds modules`/`pds launch` to consume these observations; resolve the selected executable only from the active interpreter and preserve per-module error isolation. Qualify official newer wheel(s) at the later installed-wheel gate.
