"""Suite #20 Slice C: source-reviewed, nonauthorizing attention label policy.

A structurally valid Core owner label or notice is *not* privacy-reviewed.
Only literal (module_id, code) pairs reviewed under producer issues #21/#22
may ever be assigned a producer-specific category label. No pairs have yet
been approved; every current result uses the fixed generic fallback.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

GENERIC_ATTENTION_LABEL: Final[str] = "Module attention item"
_APPROVED_IDS: Final[frozenset[str]] = frozenset(
    item.component_id for item in APPROVED_COMPONENTS if item.launchable
)

# Future entries require *separately recorded* exact-owner, exact-code,
# displayed-wording and installed-producer privacy evidence. Do not populate
# from provider report text, source discovery, Core validation or user input.
_REVIEWED_LABELS: Final[Mapping[tuple[str, str], str]] = MappingProxyType({})


def label_for_attention_category(owner_id: object, code: object) -> str:
    """Never echo unknown/unreviewed Core owner-supplied strings to teachers."""
    if type(owner_id) is not str or owner_id not in _APPROVED_IDS:
        return GENERIC_ATTENTION_LABEL
    if type(code) is not str:
        return GENERIC_ATTENTION_LABEL
    return _REVIEWED_LABELS.get((owner_id, code), GENERIC_ATTENTION_LABEL)


def allowed_attention_label(owner_id: object, label: object) -> bool:
    """Validate *displayed* literals against the Suite source-review policy."""
    return (
        type(owner_id) is str
        and owner_id in _APPROVED_IDS
        and type(label) is str
        and (
            label == GENERIC_ATTENTION_LABEL
            or label in (
                value
                for (approved_owner, _), value in _REVIEWED_LABELS.items()
                if approved_owner == owner_id
            )
        )
    )
