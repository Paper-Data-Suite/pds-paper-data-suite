"""#20D source regression: same Core-valid synthetic witness as installed gate."""

from __future__ import annotations

from scripts.issue20_d_installed_pure_smoke import run_synthetic_witnesses


def test_synthetic_core_v1_attention_witnesses() -> None:
    observed = run_synthetic_witnesses()
    assert len(observed) == 6
    assert observed[0] == "SUITE20_D_CORE_V1_PARTIAL_COVERAGE_VERIFIED"
    assert observed[-1] == "SUITE20_D_SYNTHETIC_ONLY_PRODUCERS_NOT_QUALIFIED"


def test_no_live_provider_in_witness_import_graph() -> None:
    import sys

    from scripts import issue20_d_installed_pure_smoke as smoke

    assert smoke._PRIVATE not in repr(smoke._synthetic_metadata())
    assert "scoreform" not in sys.modules
    assert "quillan" not in sys.modules
