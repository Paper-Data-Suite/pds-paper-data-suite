# Suite #52 — Teacher Home source acceptance and handoff (Slice 4)

**Ticket:** [Suite #52 — Interactive Teacher Home](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/52)
**Source baseline:** Suite feature branch `52-interactive-teacher-home`, parent commit `6d4b19f0104794a65ed0bebae4bf49534192eca5` (Slices 1–3); pinned Core source commit `a0d5e1a50580bbe025f0cad23c7e8524203a52ec`.
**Evidence status:** Source acceptance is subject to the Slice 4 Windows runner; this file alone is **not** execution evidence or an official Core v1 release attestation.

## What is actually implemented

Running `pds` with no subcommand in an interactive input **and** output session enters the injected `run_teacher_home` controller. Captured/non-TTY invocations still produce conventional `pds` help. `pds --help`, `--version`, explicit subcommands, and existing process exit codes remain owned by the original CLI.

The home lists exactly six Suite-approved applications (ScoreForm, Quillan, Concord, Meridian, Vitrine, Portia) and reports current-environment eligibility from the existing Suite registry/inventory. A selected application delegates to the **same** `cli._run_launch` path as `pds launch <id>`, which rechecks eligibility before a foreground launch. Returning from a child reopens the Suite home; only approved top-level recent-component IDs are stored by the existing launcher/settings path. Core is **not** a launchable application. Local compatibility is **not** proof of official wheel provenance, producer readiness or academic authorization.

Workspace & Classroom Management, Notes & Tasks, Process Returned Papers and Attention Needed remain **explicitly unavailable** in this shell until their owners supply and Suite qualifies real callable capabilities. Recent Applications is *application* history, not recent work-item continuation. Help and `pds doctor` are available on explicitly selected menu paths; opening the home does not invoke provider callbacks, Notes storage, a classroom menu, workspace initialization or student-record reads. Local `B/M/Q/H` behavior is confined to Suite-owned prompts, not injected into child processes.

## Source-journey acceptance

`tests/test_issue52_teacher_home_journeys.py` and `scripts/issue52_teacher_home_source_acceptance.py` exercise actual Suite controller/CLI entry behavior with **injected** terminal streams, approved synthetic inventories and no producer process. Cases include:

- Basic home and nested `B/M/Q/H` navigation, six exact applications and disabled workflows.
- Noninteractive/no-argument help instead of blocking for input; qualified header source and pre-contract header fallback remain covered by Slice 3.
- One unavailable module without blocking another, redaction of untrusted metadata/path strings, and one synthetic child nonzero-exit followed by successful synthetic launch.
- Explicit Recent Applications, CLI help and doctor; `:notes` without a validated Notes menu is **not** intercepted or persisted.
- Source-evidence JSON retaining only commit/artifact identities, synthetic scenario counts and pending gates; no workspace, settings, student identifiers, absolute paths or private Notes.

The runner stores a machine-readable synthetic source-journey result under the **user-selected external evidence directory**; it must not be checked into the repository. This synthetic run is **D1/source journey**, not a physical Windows console/ANSI VT or official wheel acceptance. The source code and test harness do not authorize provider callbacks, class/roster mutation, academic actions or deep-module return.

## Separate Core release evidence (Slice 3)

Real Windows Slice 3 result supplied by the teacher:

| Artifact / track | Recorded result |
| --- | --- |
| Pinned Core source | `a0d5e1a50580bbe025f0cad23c7e8524203a52ec` |
| Locally built, **developer-only** Core wheel | SHA-256 `62a62f4f3da06e6926832ec22d2b071449f5424aa58566ee1f1ca32120bef2ef`; Suite consumer of `terminal.header.v1` and pure `terminal.notes_command.v1` accepted |
| Official published Core v0.6.6 wheel | SHA-256 `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301`; Suite legacy **plain-text fallback** accepted |
| **Official newer Core wheel containing v1** | **PENDING — NOT RELEASE QUALIFIED** |

Full procedure and caveats: [Slice 3 two-track Core header qualification](issue52-core-header-qualification.md). A developer wheel that reports `0.6.6` does **not** become a published `0.6.6` artifact by having that version string. The two wheel digests and source-commit identity must remain distinguishable.

## Consumer handoff boundaries

| Later work | Safe existing seam | What remains to qualify |
| --- | --- | --- |
| [Suite #53](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/53) | Existing disabled Workspace & Classroom Management choice; Core public `classroom.menu.v1` when available | Validated callable Core admin service, context/identity, return handling and real installed acceptance; do not embed a second roster editor |
| [Suite #54](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/54) | Existing disabled Notes & Tasks choice and independently probed Core teacher contract | Actual `notes.records.v1` + `notes.menu.v1`, private OS-user record behavior and valid menu dispatch; `terminal.notes_command.v1` alone is insufficient |
| [Suite #17–#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17) | Disabled Process Returned Papers choice | Core-owned retain-first intake and module-owned paper routing after explicit qualification |
| [Suite #20–#23](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/20) | Disabled Attention Needed choice; separate metadata-only provider observation | Executed/read-only provider readiness and attention, truthful no-data/failure distinctions, supported owner-action refs |
| [Suite #24](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/24) | `settings.load_suite_settings().recent_components`, capped at five top-level approved IDs | Qualified module-owned work-item continuation; no fabricated deep-link or cached private record |
| [Suite #25–#26](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/25) | Existing `pds doctor`, `pds --help` via explicit teacher home choice | Further diagnostics and bundles on separate, opt-in contracts |

Later owner integrations must consume public, versioned capabilities and replace disabled entries only after tested handler and return protocols exist. A named choice does not itself grant permission, establish teacher identity or establish a producer integration contract.

## Acceptance and final release disposition

- **D0 / design:** v0.2 accepted before this issue.
- **D1 / source:** Slices 1–3 have Windows targeted tests and developer Core-wheel consumer evidence; Slice 4 synthetic source journey and regression evidence recorded by its own runner when it passes.
- **D2 / official Core v1 artifact:** **PENDING**. Official Core v0.6.6 verifies backward compatibility only.
- **D3 / installed Suite official-Core-v1 consumer and physical terminal:** **PENDING** until a newer official Core v1 wheel and supported real Windows/other terminal acceptance exist.
- **D4 / composed teacher workflows:** **PENDING** separately under #27/#28 and producer issues; not redefined as part of source-only #52.

The teacher-home source may be reviewed while D2/D3 are pending, but final green-header release qualification must be held or explicitly deferred by the milestone owner. Neither passing synthetic journeys nor using a developer Core build can silently close that gate. Do not mark Suite v0.2.0 published on the basis of this branch alone.
