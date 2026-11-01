# Slice 104 qualification

Focused tests exercise accepted read-only grants, untrusted writer permissions in every mutating bit, inherited ACEs, unknown service principals, unsafe owners, malformed ACL documents, and non-Windows refusal. Windows live query is separately exercised in a non-destructive user environment; no production installation or protected service is created.

Qualification is **Ruff check/format, strict mypy, Slice 104 focused pytest, relevant Slice 103 native-lab tests, and pip check**. Do not rerun all 2,800+ Issue #49 cases for this independent, additive audit. Full suite remains reserved for integration, release, and major boundary changes.
