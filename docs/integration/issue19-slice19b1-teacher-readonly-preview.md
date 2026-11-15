# Suite #19 — Slice 19B1: Teacher Home read-only selected-file preview

**Parent:** `e7a132f0581ccecf9b2aab4d40b390261e6b5367` on
`19-teacher-home-returned-paper-workflow`.

## User-visible change

Teacher Home option **9 — Process Returned Papers** opens a Suite-owned
**read-only preview** screen. The teacher explicitly selects option 1,
enters a bounded count of 1–8 local files and supplies each absolute PDF,
PNG or JPEG filename. Only then does the controller reuse the existing #17
`build_readonly_preflight` / `render_readonly_preflight` to report physical
page states and candidate (unverified) producer metadata. Paths, QR payloads,
and student identifiers are never echoed by the Suite screen.

B/M return to Teacher Home and Q/EOF exit. A blank count or filename cancels
selection; malformed, duplicate or relative paths are rejected without
opening files. The file-path field is treated as data, not a keyboard shortcut.
The controller catches bounded source/decoder failures without exposing raw
exception messages or interrupting Home. The existing noninteractive `pds`
CLI, six application launch options, Recent Applications, Help/Diagnostics,
and other disabled teacher-workflow entries are unchanged.

## Authority boundaries

- **Nothing is read on Home startup or menu 9 entry.** Source observation is
  explicitly requested through the file selector; no recursive discovery.
- **Nothing is written** by this controller: no `retain_source_scan`, #18
  processing plan, Core route resolution, producer import/dispatch, score,
  grade publication, Notes storage or Portia record.
- Both #19A1 admission and #19A2 payload audit remain default-deny, and
  #19A3 isolated native/profile diagnostic is **never** used by this menu.
- A readable candidate QR is not admission, route authorization, a Grade or
  proof of captured Quillan response. Existing #17 renderer controls labels.
- The implementation adds only a lazily imported Suite controller and
  narrowly modifies Teacher Home's option 9 presentation/action.

## Remaining #19 work

19B2: explicit Core `scans_inbox` inventory and snapshot-bound selection,
physical-page choice and a nonauthorizing plan. 19C–19G: first Core custody
consent, second handler consent, action-time exact installed qualification,
truthful stage/result views, Core v2 review, and installed teacher acceptance.

## Qualification

Scope validation to new controller tests, existing #52 Teacher Home tests,
#17 preflight/inbox tests, Ruff, strict mypy and staged whitespace before
committing. A later installed/native synthetic teacher journey is required;
source and mock-preview tests cannot claim functional scanner qualification.
