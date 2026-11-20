# mypy: disable-error-code="import-not-found, import-untyped"
"""#19G2B actual installed Linux default-deny with real native QR preview.

The wheelhouse is authenticated first. Neither Core custody nor any producer
route handler runs. This script is never an authorization/acceptance credential.
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

from paper_data_suite.returned_paper_installed_wheels import (
    verify_official_wheelhouse,
)
from paper_data_suite.returned_paper_live_admission import (
    inspect_live_paper_admission,
)
from paper_data_suite.returned_paper_readonly_decode import (
    observe_selected_sources,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux":
            raise ValueError("unsupported_host")
        if not args.wheelhouse.is_absolute() or args.wheelhouse.is_symlink():
            raise ValueError("wheelhouse_path")
        if not args.fixture.is_absolute() or args.fixture.is_symlink():
            raise ValueError("fixture_path")
        if len(verify_official_wheelhouse(args.wheelhouse)) != 3:
            raise ValueError("wheels_unverified")
        for distribution, version in (
            ("paper-data-suite", "0.1.0"),
            ("pds-core", "0.6.6"),
            ("scoreform", "0.13.0"),
            ("quillan", "0.10.6"),
        ):
            if metadata.version(distribution) != version:
                raise ValueError("installed_version")
        read_only = observe_selected_sources((args.fixture,))
        if (
            len(read_only) != 1
            or read_only[0].status != "observed"
            or len(read_only[0].pages) != 2
            or tuple(page.candidate_module_id for page in read_only[0].pages)
            != ("scoreform", "quillan")
            or any(
                page.status != "candidate_unverified"
                for page in read_only[0].pages
            )
        ):
            raise ValueError("native_read_only")
        status = inspect_live_paper_admission(args.wheelhouse)
        if (
            status.status != "unsupported_runtime"
            or status.qualified_modules != frozenset()
            or status.can_skip_second_consent is not False
            or status.source_retention_authorized is not False
        ):
            raise ValueError("linux_admission_not_denied")
    except (Exception, KeyboardInterrupt):
        # No arbitrary exception messages, paths or QR content.
        print("SUITE19_G2B_LINUX_DEFAULT_DENY_REFUSED", file=sys.stderr)
        return 2
    print("SUITE19_G2B_LINUX_INSTALLED_WHEELS_VERIFIED")
    print("SUITE19_G2B_LINUX_NATIVE_PREVIEW_TWO_PAGES_VERIFIED")
    print("SUITE19_G2B_LINUX_LIVE_DISPATCH_DEFAULT_DENY_VERIFIED")
    print("SUITE19_G2B_LINUX_SYNTHETIC_ONLY_NO_PRODUCER_DISPATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
