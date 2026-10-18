# Issue #49 — Slice 15: Cooperative prior-bound activation intent

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `eb03af94c5b83aa58b40c49478a121dfd01a5946`
**Status:** Additive update-journal infrastructure; not a production activation.

## Purpose

Slice 14 introduced `verify_prior_bound_candidate`, which independently checks
both old and proposed software bytes but does not record anything. The existing
Slice 11 `request_activation_intent` can arm a journal based solely on the
candidate and cannot require a verified prior installation when an expected
prior record digest is present. Slice 15 provides an **alternative**,
`arm_prior_bound_update_intent`, for prior-bound transactions.

## Operation and lock order

1. Check exact positive expected journal revision and timezone-aware time.
2. Verify the software root does not overlap the classroom workspace.
3. Acquire the existing global candidate-selection lock, then the exact
   transaction journal lock. Both are exclusive and cooperative; this order
   is compatible with the existing Slice 12 selector.
4. Refuse any pending candidate-selection recovery marker.
5. Read the unarmed journal and require the expected revision, correct phase,
   and non-regressing observation timestamp.
6. Call Slice 14 two-sided preflight **while those locks are held**. This
   freshly rechecks the previous selection/receipt observation, prior wheelhouse
   and native evidence, candidate signed wheelhouse/native evidence, directory
   separation, and exact journal bindings.
7. Atomically replace the journal with revision + 1 in `activation_intent`;
   release both locks on success or failure.

The function deliberately makes **no candidate-pointer change**. A failed
preflight leaves the prior journal byte-for-byte intact; a failed atomic
replacement never records a successful intent. Cooperating writers cannot
change the selection or journal during verification. Arbitrary same-user
writes outside these locks remain a threat and are not treated as trusted.

The existing generic `request_activation_intent` remains available for
preexisting code paths; the prior-bound coordinator must be explicitly used
when previous-installation evidence is required. Production integration will
need one unified policy so a caller cannot bypass that requirement.

## Explicit non-authority boundary

The locally editable previous observation, selection pointer, and journal do
not prove that a previous installation was historically active or trusted.
The function does not issue an installed-state receipt, authorize launching,
run pip, execute the candidate environment, change Core or any PDS module,
or touch classroom data. Slice 12's generic selector still refuses a previous
receipt claim, so no production rollout occurs through this route yet.

Remaining work: protected prior-installation continuity, real candidate
installation and smoke acceptance, jointly guarded reversible slot switching,
managed launcher integration, release publication and teacher-facing planning.
