# Suite #52 — Core header consumer qualification (Slice 3)

**Source baselines:** Suite feature branch `52-interactive-teacher-home` at `edb91a313edb93c3eaf43847cd15916561fa865f` before this slice; Core source commit `a0d5e1a50580bbe025f0cad23c7e8524203a52ec` (Core #237). **Release observation (2026-11-07):** published Core v0.6.6, `pds_core-0.6.6-py3-none-any.whl`, SHA-256 `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301`.

## What this qualification distinguishes

| Evidence | What is tested | What is *not* established |
| --- | --- | --- |
| **Track A: pinned development source wheel** | Archive the exact Core Git commit independently of the Core checkout's dirty/active branch; build a **developer-only** wheel without network/build isolation; run an isolated interpreter using this wheel as import authority; inspect Core's actual advertised `terminal.header.v1` and `terminal.notes_command.v1`, exercise public header render/print and parser vectors, and invoke the Suite home using its **real** Core printer. Save the developer wheel SHA-256. | This is **not** an official published Core wheel, even though metadata still reports `0.6.6`. It is not evidence for release identity or terminal ANSI behavior on a real Windows console. |
| **Track B: verified published v0.6.6** | Verify exact published wheel SHA-256 and metadata, then launch an **independent** isolated consumer probe. Confirm pre-contract Core is detected, the Suite home uses readable plain text, and no Notes command/handler is falsely available. | The published v0.6.6 artifact does **not** supply Core #237's v1 header, so a green-header **official release D2/D3 gate remains pending**. |
| **Synthetic regression tests** | Refuse wrong wheel hashes, misleading metadata, invalid wheels, changed Git working-tree content, malformed isolated results and missing argument boundaries. | Synthetic tests do not replace either real wheel probe. |

Both probes use `python -I -B`, put **one selected wheel** ahead of installed packages, verify that `pds_core.__file__` originates from that wheel, and avoid installation or copying to production site-packages. Core source is exported with `git archive` from a pinned commit: **no Core checkout or branch manipulation**. The only retained files are a clearly labeled developer wheel and a non-sensitive JSON evidence report under the user-selected output directory; tests use fake app inventories and `q` so no private teacher data, settings writes, provider callbacks, or subprocess module launch occur.

## Local acceptance (runner invokes this automatically)

The following command is illustrative; use the guarded Slice 3 runner supplied with the implementation to apply the files, validate, record acceptance, commit and push only on success.

```powershell
& .\.venv\Scripts\python.exe scripts\issue52_core_header_acceptance.py `
    --core-repo "C:\Dev\Python\Paper-Data-Suite\pds-core" `
    --suite-root "C:\Dev\Python\Paper-Data-Suite\pds-paper-data-suite" `
    --official-core-wheel "$HOME\Downloads\pds16_official_wheels\pds_core-0.6.6-py3-none-any.whl" `
    --output-root "$HOME\Downloads\suite52_core_header_acceptance"
```

Preconditions: the target Core SHA must be locally available in Git; the **unchanged official** v0.6.6 wheel must be on disk; the invoking virtual environment must have local `pip` and a compatible build backend (`setuptools>=77`). The acceptance tool uses `--no-deps --no-build-isolation --no-index` and **does not fetch packages or change the live Core environment**. If any prerequisite is missing, acceptance stops; it never supplies a guessed artifact or silently substitutes another Core wheel.

On success, the command prints `SUITE52_S3_DEV_HEADER_AND_PARSER_ACCEPTED`, `SUITE52_S3_OFFICIAL_LEGACY_FALLBACK_ACCEPTED`, and `SUITE52_S3_OFFICIAL_V1_HEADER_RELEASE_PENDING`. The JSON evidence report records Core source SHA, developer wheel SHA, official wheel SHA, Python/OS, consumer outcomes and explicit pending gate without paths or classroom data. Do **not** publish the developer wheel as an official release; the retained file is for controlled source verification only.

## Remaining release/terminal gates

- An **official later Core wheel** actually exporting v1 symbols must be released and verified against its specific publisher artifact. The current official Core v0.6.6 *fails to supply* those symbols by design; Track B here is a **legacy fallback check**, not v1 qualification.
- Real Windows terminal/ANSI VT support, `NO_COLOR`, redirected output and TTY input/output must be acceptance-tested in a supported terminal. Static `render_teacher_header(ansi=True)` is only a deterministic render vector, not evidence that an active console supports styling.
- The Notes record/menu (`notes.menu.v1`) and classroom administration (`classroom.menu.v1`) remain separately gated under Core #238–#243 / Suite #53–#54. This script never invokes those capabilities.
- For #52 final disposition, cite exact logged hashes and distinguish *source implemented*, *developer wheel consumer accepted*, *published legacy fallback accepted*, and *new official v1 header consumer pending*. Update [Suite's contract matrix](teacher-experience-contract-matrix.md) with the actual outcomes after the Windows acceptance completes.
