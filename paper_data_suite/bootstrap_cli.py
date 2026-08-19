"""Internal command-line support for the verified Windows bootstrap workflow."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from paper_data_suite.bootstrap import (
    BootstrapPlan,
    BootstrapPlanningError,
    EnvironmentMarkerIdentity,
    build_bootstrap_plan,
    normalize_distribution_name,
)
from paper_data_suite.bootstrap_artifacts import (
    BootstrapArtifactError,
    pds_constraints_text,
    required_component_artifacts,
    verify_required_artifacts,
    write_pds_constraints,
)
from paper_data_suite.bootstrap_installation import (
    BootstrapInstallationError,
    verify_installed_composition,
    verify_installed_import_layout,
)
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
    release_compatibility_manifest_sha256,
)
from paper_data_suite.environment_inspection import (
    EnvironmentInspectionError,
    inspect_windows_environment,
    write_environment_marker,
)


def _manifest_summary() -> dict[str, object]:
    manifest = load_release_compatibility_manifest()
    return {
        "suite_distribution": manifest.suite.distribution,
        "suite_version": manifest.suite.version,
        "compatibility_manifest_sha256": release_compatibility_manifest_sha256(),
        "python_specifier": manifest.python.specifier,
        "tested_minors": list(manifest.python.tested_minors),
        "optional_component_ids": [
            item.component_id for item in manifest.components if not item.required
        ],
    }


def _plan_payload(plan: BootstrapPlan) -> dict[str, object]:
    return {
        "suite_version": plan.suite_version,
        "compatibility_manifest_sha256": plan.compatibility_manifest_sha256,
        "can_apply": plan.can_apply,
        "changes_required": plan.changes_required,
        "environment": {
            "path": plan.environment.path,
            "action": plan.environment.action,
            "python_version": plan.environment.python_version,
            "python_minor": plan.environment.python_minor,
            "python_qualified": plan.environment.python_qualified,
            "exists": plan.environment.exists,
        },
        "packages": [
            {
                "component_id": item.component_id,
                "display_name": item.display_name,
                "distribution": item.distribution,
                "desired_version": item.desired_version,
                "installed_version": item.installed_version,
                "required": item.required,
                "selected": item.selected,
                "action": item.action,
                "reason": item.reason,
            }
            for item in plan.packages
        ],
        "external_prerequisites": [
            {
                "prerequisite_id": item.prerequisite_id,
                "kind": item.kind,
                "commands": list(item.commands),
                "platforms": list(item.platforms),
                "purpose": item.purpose,
                "required_by": list(item.required_by),
            }
            for item in plan.external_prerequisites
        ],
        "blockers": [
            {
                "code": item.code,
                "message": item.message,
                "component_id": item.component_id,
                "distribution": item.distribution,
            }
            for item in plan.blockers
        ],
        "warnings": [
            {"code": item.code, "message": item.message}
            for item in plan.warnings
        ],
    }


def _format_plan(plan: BootstrapPlan) -> str:
    lines = [
        "Paper Data Suite bootstrap plan",
        "",
        f"Suite: {plan.suite_version}",
        f"Compatibility manifest SHA-256: {plan.compatibility_manifest_sha256}",
        f"Python: {plan.environment.python_version}",
        "Qualified by suite: "
        + ("yes" if plan.environment.python_qualified else "no"),
        f"Environment: {plan.environment.path}",
        f"Environment action: {plan.environment.action}",
        "",
        "Packages:",
    ]
    for package_plan in plan.packages:
        installed = package_plan.installed_version or "not installed"
        lines.append(
            f"  {package_plan.display_name} {package_plan.desired_version}: "
            f"{package_plan.action} (installed: {installed})"
        )

    lines.extend(["", "External prerequisites:"])
    if plan.external_prerequisites:
        for prerequisite_plan in plan.external_prerequisites:
            lines.append(
                "  "
                + ", ".join(prerequisite_plan.commands)
                + f" ({prerequisite_plan.purpose}); required by "
                + ", ".join(prerequisite_plan.required_by)
                + "; not managed by bootstrap"
            )
    else:
        lines.append("  none declared for selected optional components")

    lines.extend(["", "Plan blockers:"])
    if plan.blockers:
        lines.extend(f"  - {item.message}" for item in plan.blockers)
    else:
        lines.append("  none")

    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"  - {item.message}" for item in plan.warnings)

    lines.extend(["", "No changes have been made."])
    return "\n".join(lines)


def _artifact_requirement_payload(
    manifest: ReleaseCompatibilityManifest,
    plan: BootstrapPlan,
) -> dict[str, object]:
    return {
        "required_artifacts": [
            {
                "component_id": item.component_id,
                "display_name": item.display_name,
                "distribution": item.distribution,
                "version": item.version,
                "repository": item.repository,
                "tag": item.tag,
                "wheel": item.wheel,
                "sha256": item.sha256,
                "url": item.url,
            }
            for item in required_component_artifacts(manifest, plan)
        ],
        "constraints": pds_constraints_text(manifest).splitlines(),
    }


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--environment-path", type=Path, required=True)
    parser.add_argument("--seed-python-version", required=True)
    parser.add_argument("--component", action="append", default=[])


def _tracked_pds_distributions(
    manifest: ReleaseCompatibilityManifest,
) -> frozenset[str]:
    return frozenset(
        {
            normalize_distribution_name(manifest.suite.distribution),
            *(
                normalize_distribution_name(item.distribution)
                for item in manifest.components
            ),
        }
    )

def _load_plan(args: Any) -> tuple[ReleaseCompatibilityManifest, BootstrapPlan]:
    manifest = load_release_compatibility_manifest()
    snapshot = inspect_windows_environment(
        args.environment_path,
        seed_python_version=args.seed_python_version,
        tracked_distributions=_tracked_pds_distributions(manifest),
    )
    plan = build_bootstrap_plan(
        manifest,
        compatibility_manifest_sha256=release_compatibility_manifest_sha256(),
        environment=snapshot,
        selected_component_ids=args.component,
    )
    return manifest, plan


def _installed_payload(
    manifest: ReleaseCompatibilityManifest,
    args: Any,
    *,
    finalize_marker: bool,
) -> dict[str, object]:
    snapshot = inspect_windows_environment(
        args.environment_path,
        seed_python_version=args.seed_python_version,
        tracked_distributions=_tracked_pds_distributions(manifest),
    )
    verified = verify_installed_composition(
        manifest,
        snapshot,
        selected_component_ids=tuple(args.component),
    )
    verify_installed_import_layout(
        manifest,
        snapshot,
        selected_component_ids=tuple(args.component),
    )
    marker_path: str | None = None
    if finalize_marker:
        marker = EnvironmentMarkerIdentity(
            suite_version=manifest.suite.version,
            compatibility_manifest_sha256=release_compatibility_manifest_sha256(),
        )
        marker_path = str(
            write_environment_marker(args.environment_path, marker)
        )
    return {
        "python_version": snapshot.python_version,
        "verified_packages": [
            {
                "component_id": item.component_id,
                "distribution": item.distribution,
                "version": item.version,
            }
            for item in verified
        ],
        "marker_path": marker_path,
    }

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("manifest-summary")
    summary.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan")
    _add_plan_arguments(plan)
    plan.add_argument("--json", action="store_true")

    requirements = subparsers.add_parser("artifact-requirements")
    _add_plan_arguments(requirements)
    requirements.add_argument("--json", action="store_true")

    verify = subparsers.add_parser("verify-artifacts")
    _add_plan_arguments(verify)
    verify.add_argument("--artifact-dir", type=Path, required=True)
    verify.add_argument("--constraints-path", type=Path, required=True)
    verify.add_argument("--json", action="store_true")

    installed = subparsers.add_parser("verify-installed")
    _add_plan_arguments(installed)
    installed.add_argument("--json", action="store_true")

    finalize = subparsers.add_parser("finalize-environment")
    _add_plan_arguments(finalize)
    finalize.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "manifest-summary":
            payload = _manifest_summary()
            print(json.dumps(payload, sort_keys=True))
            return 0

        if args.command in {"verify-installed", "finalize-environment"}:
            manifest = load_release_compatibility_manifest()
            payload = _installed_payload(
                manifest,
                args,
                finalize_marker=args.command == "finalize-environment",
            )
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    "Installed PDS composition verified"
                    + (
                        " and environment marker finalized."
                        if args.command == "finalize-environment"
                        else "."
                    )
                )
            return 0

        manifest, plan = _load_plan(args)
        if not plan.can_apply:
            if args.json:
                print(json.dumps(_plan_payload(plan), sort_keys=True))
            else:
                print(_format_plan(plan))
            return 3

        if args.command == "plan":
            if args.json:
                print(json.dumps(_plan_payload(plan), sort_keys=True))
            else:
                print(_format_plan(plan))
            return 0

        if args.command == "artifact-requirements":
            requirements = required_component_artifacts(manifest, plan)
            payload = _artifact_requirement_payload(manifest, plan)
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                for requirement in requirements:
                    print(
                        f"{requirement.component_id}: {requirement.url}"
                    )
            return 0

        verified = verify_required_artifacts(
            manifest,
            plan,
            args.artifact_dir,
        )
        constraints = write_pds_constraints(
            args.constraints_path,
            manifest,
        )
        payload = {
            "verified_artifacts": [
                {
                    "component_id": item.component_id,
                    "distribution": item.distribution,
                    "version": item.version,
                    "path": item.path,
                    "sha256": item.sha256,
                }
                for item in verified
            ],
            "constraints_path": str(args.constraints_path.resolve()),
            "constraints": constraints.splitlines(),
        }
    except (
        BootstrapPlanningError,
        BootstrapInstallationError,
        CompatibilityManifestError,
        EnvironmentInspectionError,
        OSError,
    ) as error:
        print(f"Bootstrap planning failed: {error}")
        return 2
    except BootstrapArtifactError as error:
        print(f"Bootstrap artifact preparation failed: {error}")
        return 4

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "Bootstrap artifacts passed: exact required component wheels "
            "authenticated and transient PDS constraints generated."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
