# Installed application discovery and launching

The Paper Data Suite shell provides a bounded application inventory and launcher for
applications explicitly qualified by the compatibility manifest bundled in the
installed `paper-data-suite` wheel.

These commands are suite orchestration. They do not transfer ownership of module
records, business rules, menus, or workflows to the suite.

## Commands

List the launchable applications known to this exact suite release:

```powershell
pds modules
```

Launch one application by its stable suite component ID:

```powershell
pds launch scoreform
pds launch quillan
pds launch concord
pds launch vitrine
```

Equivalent module invocations are:

```powershell
python -m paper_data_suite modules
python -m paper_data_suite launch scoreform
```

`pds launch` accepts a component ID, not an executable name, import path,
distribution name, filesystem path, URL, or arbitrary command line.

## Release authority

Application discovery is driven by the suite's bundled release-compatibility
manifest plus installed Python distribution metadata.

A component is listed as an application only when its manifest row declares:

```text
launchable_application
```

This is deliberately independent of Core routing and publication profiles.

Consequently:

- Vitrine is a launchable application even though it is not a Core routing module;
- Core is not a launchable application merely because the Core wheel exposes its
  own console scripts;
- an undeclared package is not promoted into the suite application inventory merely
  because it looks like a PDS package or exposes a similarly named command;
- Meridian and Portia are not fabricated as current suite applications when they
  are absent from the active qualified composition.

The manifest also owns the teacher-facing application name and bounded purpose
text. The shell does not maintain a second application catalog.

## Inventory statuses

`pds modules` reports one of four states for each manifest-qualified launchable
application.

### `AVAILABLE`

The application is eligible for launch because the shell has proved the bounded
software trust conditions required for launching:

- the running Python minor is suite-qualified;
- the installed suite distribution matches its bundled manifest;
- required Core is installed at the exact suite-qualified version;
- the application distribution is installed at the exact qualified version;
- its expected public console-script metadata has the exact name, target, and
  owning distribution without a foreign conflict;
- the corresponding launcher resolves inside the running Python environment's
  scripts directory and satisfies the platform-specific launcher checks.

`AVAILABLE` does **not** mean that every module workflow is ready, that a workspace
exists, or that every optional/external prerequisite for every module feature is
healthy. Use `pds doctor` for broader environment diagnostics.

### `NOT_INSTALLED`

The application is qualified by this suite release but its optional distribution
is absent.

This is a normal partial-installation state and does not make `pds modules` fail.

### `INCOMPATIBLE`

The application is present, but a release-trust requirement is contradictory or
unsafe, such as a wrong qualified package version, unqualified Python/Core state,
or mismatched/conflicting public console metadata.

The shell will not launch an incompatible application.

### `UNAVAILABLE`

The package and public metadata otherwise qualify, but the shell cannot establish a
safe usable launcher in the current Python environment.

The shell will not substitute another command found on `PATH`.

## Safe launcher resolution

The suite never launches a sibling application by searching `PATH` for a bare
command name.

After validating installed distribution and console-entry-point metadata, it derives
the scripts directory belonging to the **running Python environment** and resolves
the manifest-declared launcher there.

This prevents a foreign executable earlier on `PATH` from silently replacing the
suite-qualified application.

Launcher resolution is platform-aware. It also rejects paths that escape the
current environment through symlink resolution or otherwise fail the bounded
launcher checks.

## Process boundary

Sibling applications are launched out of process through their declared public
console boundary.

The suite does not import private sibling CLI or menu modules to launch an
application.

The child process:

- runs in the foreground;
- inherits the current working directory;
- inherits standard input, output, and error so the application's interactive menu
  remains usable;
- is started without a shell;
- receives the normal environment except inherited `PYTHONPATH` entries are removed
  to prevent source-checkout shadowing;
- retains legitimate environment context such as `PDS_WORKSPACE_ROOT`.

The suite does not add application-specific arguments in this issue. Advanced or
module-specific command-line operations remain available through each component's
own direct CLI.

## Failure and exit semantics

`pds modules` returns `0` when the inventory itself completes, including when one
or more optional applications are absent, incompatible, or unavailable. Those
states are inventory facts rather than command failure.

`pds launch <component-id>` fails closed when the requested application cannot be
safely launched.

Important cases include:

- unknown component ID: command/request usage failure;
- known component that is not a launchable application, such as Core: refused;
- qualified application not installed: refused;
- incompatible application: refused;
- unavailable safe launcher: refused;
- child process cannot be started: bounded launch failure;
- child application exits nonzero: the suite returns a nonzero launch result
  without interpreting or rewriting module-owned semantics.

The shell does not automatically install, upgrade, downgrade, repair, or replace a
component in response to these states.

## Workspace and privacy boundary

Listing applications does not require a workspace and must not create, select,
initialize, or inspect classroom records.

Launching a module also does not make the suite the owner of that module's
workspace behavior. Once the verified public application boundary is entered, the
application and Core continue to own their respective workflows and shared
infrastructure.

Normal inventory and launch-refusal output is bounded to package/application
identity, status, and concise remediation. It must not expose student records,
answers, scores, writing, behavior narratives, scans, credentials, raw environment
dumps, private entry-point internals, or arbitrary filesystem contents.

## Relationship to `pds doctor`

Application discovery and `doctor` share neutral installed-distribution and
entry-point inspection primitives so the shell does not maintain contradictory
definitions of installed package identity.

Their responsibilities remain different:

```text
pds modules / pds launch
    -> application qualification and safe launch boundary

pds doctor
    -> broader environment, dependency, workspace, registry, and readiness health
```

The launcher does not become a second diagnostic framework. In particular, missing
Poppler or a currently absent workspace does not by itself prevent opening an
otherwise qualified application menu.

## Installed-wheel acceptance

Release validation must exercise discovery from the built wheel outside the source
tree.

`scripts/smoke_test_wheel.py` creates an isolated environment containing the suite
wheel and exact Core wheel supplied to it, removes source-shadowing inputs, runs
from an unrelated empty directory, and verifies both:

```text
python -m paper_data_suite modules
pds modules
```

With no optional sibling wheels installed, every qualified application must remain
visible as `NOT_INSTALLED` and the command must succeed.

The smoke test also places a foreign same-named application command on `PATH` and
proves that it neither changes inventory classification nor gets executed when the
suite refuses to launch the absent application.

The existing focused launch tests separately exercise exact current-environment
launcher resolution, symlink escape rejection where supported, foreground
subprocess execution, environment sanitation, process-start failure, and child
nonzero exit propagation.

Run the partial-install package acceptance flow with:

```powershell
python .\scripts\check_package.py <suite-wheel>
python .\scripts\smoke_test_wheel.py <suite-wheel> <core-wheel>
```

Before issue completion, also run the full qualified-application composition smoke
with an artifact directory containing every exact component wheel declared by the
active manifest:

```powershell
python .\scripts\smoke_test_application_wheels.py `
  <suite-wheel> `
  --artifact-dir <directory-containing-declared-wheels>
```

The full-composition smoke first authenticates the component artifact directory
against the compatibility manifest. It then creates a fresh virtual environment,
installs the exact Core and application wheels plus the built suite wheel, resolves
ordinary third-party Python dependencies, and requires both module-form and
installed-console `pds modules` output to report every qualified application as
`available`.

It prepends foreign same-named commands to `PATH`, invokes the installed `pds`
launcher directly, feeds the normal `Q` quit action to every current supported
application menu, requires each launch to return success, and verifies that the
foreign commands and synthetic workspace are untouched. On Windows the launcher
under test is the environment's installed `pds.exe`.
