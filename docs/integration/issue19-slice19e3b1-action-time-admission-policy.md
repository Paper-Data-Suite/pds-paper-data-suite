# Suite #19E3B1 — Reviewed current-runtime eligibility boundary

Issue: [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
Branch: `19-teacher-home-returned-paper-workflow`
Exact parent: `e0b7478c25ccbc2bf24ea080b872ca779046e33e`

## What is now established

The opt-in 19E3A installed acceptance on Windows Python 3.11.9 succeeded for
three independently SHA-256-verified published wheels: Core 0.6.6, ScoreForm
0.13.0, Quillan 0.10.6. It built and installed Suite 0.1.0 into a disposable
venv, passed `pip check`, current launcher and native checks, and completed the
#18 synthetic Core-retained mixed-PDF dispatch rehearsal, including first and
second cancellations and an issued ScoreForm 4/4 sheet plus a Quillan handler
return. The teacher Home program was **not** exercised; no real student data
were accessed. The installed runtime check used Pillow 12.3.0, PDFium 5.15.2
and ZXing-cpp 2.3.0 on Windows x64.

## B1 policy (narrow, opt-in, no handler call)

New `returned_paper_live_admission.inspect_live_paper_admission(wheelhouse)`
accepts only an explicit absolute, existing, non-symlinked wheelhouse. It
rejects non-Windows, non-x64 and non-Python-3.11 hosts before touching installed
modules. It then invokes the **built-in** 19E1 readiness audit, rather than
accepting a diagnostic object, caller-selected module set, external flag or
written acceptance marker. E1 rechecks #49 local launchers and dependencies,
`pip check`, published wheel SHA and on-disk installed payloads, native version
and exported API surfaces, and installed Core registry/profile compatibility.
Only a consistent current `diagnostic_match_not_admitted` observation yields an
*ephemeral* `LivePaperAdmissionV1('admitted', {'scoreform','quillan'})`.
All other outcomes yield **empty** `qualified_modules`. This v1 policy is an
**all-or-nothing exact pair**, not an assertion that a single installed module
is sufficient. Partial producer readiness and preserving a qualified sibling
when the other is missing remain **open acceptance items**, not claimed here.

No payload or `dist-info` audit can cryptographically prove the origin of
native DLLs currently mapped into a process, or defend against malicious
same-account time-of-check/time-of-use replacement. This is a scoped local
installed-composition decision grounded in controlled release-wheel
acceptance, **not** a general publisher authentication service. It does not
update Suite #49 immutable historical compatibility manifests, enable an
unknown producer, or change #18 Core ownership.

The result cannot be stored, replayed, or treated as a bearer credential. A
future invocation of `execute_with_core_review` must obtain a **new decision
immediately before action**, use only its exact qualified set, and still obtain
#18's fresh retained-byte verification and separate teacher approval through
19D2's `DispatchReviewV1`/`DispatchDecisionV1` callback. Approval does not
imply academic publication, grade transfer, or Quillan evidence capture.

**19E3B1 itself imports no Core dispatcher, invokes no handler, and changes no
Teacher Home menu.** It is a reviewed policy primitive only. 19E3B2 must wire
it with Core, navigation and cancellation, including testable no-replay and
partial/uncertain reporting; 19G must qualify actual wheel-installed teacher
UI and Linux counterpart before production handoff.

## Qualification

- Unit tests deny unsupported hosts, missing/linked wheelhouses, malformed or
  throwing E1 observations, unqualified and contradictory candidate states,
  and fabricated/partial grants; they verify the exact x64 two-owner policy.
- A guarded Windows source runner verifies exact clean branch/remote parent,
  hashes, pytest, Ruff, strict mypy, compile and staged Git file list before
  commit/push. It does not re-run E3A's potentially expensive installed native
  rehearsals, and cannot turn synthetic unit monkeypatches into live admission.
- Native acceptance is already recorded from the **user's actual E3A log**;
  the current development `.venv` has not itself passed the 3.11/native gate.
