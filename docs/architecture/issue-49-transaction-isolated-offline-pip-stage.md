# Issue #49 — Slice 68: Transaction-isolated offline pip staging

## Scope and dependency order

Slice 66 verifies a complete root-signed wheel lock and every selected PDS wheel's delegated publisher release. Slice 67 reconciles an **already installed** staged candidate with its plan and independently signed native evidence. Slice 68 fills the intervening operational gap: an **explicitly consented, local write** that constructs a transaction-specific isolated virtual environment and installs exactly the signed wheel files with pip. It does **not** replace Slice 67, which must still be run after independent native evidence is provided.

`install_authenticated_plan_to_isolated_stage` is deliberately a library-level transaction primitive, not a new `pds update` production action. Existing launch, default modules/doctor, update planning, and classroom workspace choices are unchanged. A production caller must first independently provision the trusted keyring and query a fresh external installation witness. Merely passing Python observation objects does not prove those preconditions; the API does **not** establish active-state authority.

## Exact write boundary

The caller supplies a canonical managed `software_root` and a distinct existing `classroom_workspace`; the Suite-owned update-journal safe-root/path checks exclude reparse roots, workspace overlap, and paths outside the software tree. There is **no caller-supplied destination for installation**. The path is fixed to `software_root/candidate-builds/<32-character lowercase hex transaction ID>` and must not exist. The authenticated wheelhouse must be an existing ordinary directory within `software_root` and separate from candidate-builds. The existing candidate-selection lock is held throughout signed preflight, local interpreter/pip subprocess execution, and post-install verification. Lock contention fails closed.

## Signed preflight and installation

1. Require the exact, explicit `INSTALL_AUTHENTICATED_WHEELS_IN_NEW_ISOLATED_STAGE` consent token; validate all inputs and require Python/platform to match the running Suite host. This token is not a remote or durable authorization credential.
2. Independently recompute the Slice 66 plan-bound signed wheelhouse proof under the cooperating selection lock. Reconstruct the Slice 7 prepared transaction record from the same signed wheelhouse and compare it to the complete planned PDS/transitive wheel inventory using Slice 67's `_match_prepared` invariant. Repeat signed preflight before creating the transaction directory.
3. Construct a new virtual environment using the current Suite interpreter, `python -m venv --copies --without-pip` (no network or installed-module import). Use **host pip's `--python <new venv>` support**, available in pip 22.3+, to install only the absolute paths of exactly the signed local wheels. Run pip with `--no-index --no-deps --no-cache-dir --no-compile --disable-pip-version-check --no-input`, a stripped environment, `PIP_CONFIG_FILE` disabled, no package-index/proxy inheritance, no source builds, no resolver, and no extra wheel selection. Both subprocesses are bounded and have no console/stdin exposure. An unsupported host pip fails safely, without network fallback.
4. Run the existing publisher-bound, real-pip installed-file/entry-point inspection. Reconcile transaction, managed locations, registry/lock digest, and signed console-owner set. Recheck the complete signed wheelhouse. Return only a transient unselected-stage observation plus an **untrusted, canonical prepared-record byte sequence**.

## Failure and authorization boundary

A partial transaction directory may remain if venv, pip, or post-install qualification fails. It is **not selected or launchable**, and the failing primitive does not delete potentially replaced filesystem contents. A controlled recovery/retention transaction must resolve it separately. The current active environment is never modified, switched, or rolled back by this primitive, and classroom data is never accessed or mutated. Existing local locks do not defend against a malicious same-user process, or against mutation after the lock is released.

Successful pip installation is **not** a signed native executable inventory, completed Slice 67 stage verification, protected installed-state receipt, current activation decision, or launch approval. Independently signed native evidence must be obtained after installation; controlled active receipt, recovery, activation and foreground launch are later boundaries. Native code is not authenticated by the staging operation. This API executes a local trusted host Python/pip toolchain and thus assumes those host tools themselves are operationally trusted.

## Verification strategy

Use synthetic signed test data with the earlier root/publisher verifiers in their independent suites; Slice 68 tests isolate orchestration only. Negative tests prove no subprocess before consent, lock, plan and prepared-record checks; exact-wheel `pip` argument shape; rejection of out-of-root targets and overlaps; incomplete-stage nonselection after partial failures; and post-install mismatch/lock drift rejection. A separate disposable actual-pip smoke checks `--python` against a wheel installed into a `--without-pip` virtualenv. Full Windows x64/ARM64 installed wheel qualification remains required for production acceptance.
