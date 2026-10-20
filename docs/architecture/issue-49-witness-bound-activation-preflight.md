# Issue #49 — Witness-bound activation preflight (Slice 38)

Slice 38 connects the signed prior-installation witness (Slices 32–37), an
existing candidate-selection pointer (Slice 12), and a prospective update
journal (Slices 11 and 25). It does not activate software.

## Read-only decision sequence

`inspect_witness_bound_update_preflight` accepts explicitly provisioned
witness transport and pinned Ed25519 public key, a canonical previous active
receipt, a previously acquired journal-bound candidate observation, exact
candidate envelope bytes and previous-slot observation record, and an explicit
software/classroom root boundary.

1. Require canonical previous receipt and unarmed `candidate_verified`
   journal at revision 1. An already armed, aborted, or recovery-pending
   transaction is not eligible.
2. Require the old local selection to match the previous receipt transaction,
   stage, generation, prepared digest, and native-evidence envelope digest.
3. Bind the candidate's observed transaction/stage/wheelhouse to the journal
   and compare the journal's exact envelope hashes against supplied bytes.
4. Bind the journal's older previous-slot *observation record* hash to the
   exact provided observation. This record is **different from the prior active
   receipt**, which is independently authenticated by the witness.
5. Reject missing, unsafe, overlapping, or nested prior/candidate software
   directories. Keep software outside the Core classroom workspace.
6. Issue a fresh challenge to the independent witness and require an
   authenticated, unexpired signed head for the prior **active receipt**.
7. Re-read the local journal/selection and reject ordinary drift during the
   witness query. Return `PRECHECK_ONLY_NOT_AUTHORIZED` with previous/proposed
   generations and exact evidence fingerprints.

## Important trust limits

- A Python `ObservedJournalPipCandidate` object is **not a credential**. Its
  caller must rerun the real signed-publisher, installed pip-file, and native
  byte audit under controlled update locks before any activation.
- Re-reading local state before/after the witness query is not an atomic
  snapshot or a defense against a hostile same-user process that can replace
  and restore files. A privileged activation writer must enforce a consistent
  transaction boundary, with crash-safe rollback.
- Neither HTTPS connectivity nor a signed response alone establishes that
  the witness runs under separate OS permissions and is independently
  administered. Both trust pins and deployment qualification remain external.
- This function does **not** arm the journal, commit the witness, write or
  switch a slot pointer, launch a module, load provider code, write a receipt,
  or change the classroom workspace. It intentionally grants no `can_launch`
  or activation capability. It is operator-initiated; normal `pds launch` is
  unchanged and remains offline.
- A prior witnessed receipt does not authenticate the proposed installation;
  it establishes only the previous checkpoint in the update transition.

## Next operational work

A production transition still requires independently qualified witness/key
custody, fresh real-wheel and Core-contract qualification, locked candidate
reverification, consent, a crash-safe commit protocol between local selection
and remote witness CAS, rollback/recovery disposition, and teacher-facing
`pds modules`, `pds doctor`, `pds update`, and `pds launch` wiring. No shortcut
from this preview to launch permission is allowed.
