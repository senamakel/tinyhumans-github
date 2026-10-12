# TinyHumans module CI contract

Module repositories call the reusable workflow at
`.github/workflows/module-ci.yml` in `tinyhumansai/.github`. The workflow
publishes the same required check names in every caller:

- `fmt`
- `clippy`
- `test`
- `coverage`
- `docs`
- `msrv`
- `supply-chain`
- `module-e2e (ubuntu-latest)`, `module-e2e (macos-latest)`,
  `module-e2e (windows-latest)`
- `feature-tests (ubuntu-latest)`, `feature-tests (macos-latest)`,
  `feature-tests (windows-latest)`

Each module owns its test commands and platform dependencies. The workflow
caller supplies repository-relative Bash scripts for its coverage gate, loader
suite, and feature suite, and any Ubuntu packages needed
to build or test it. The shared workflow validates those script paths before
running them. The `test` job runs
the default feature set; the feature-test script runs on all three operating
systems. The MSRV job and each module-e2e runner read `rust-version` from Cargo
metadata. For a concrete workspace, the root package declaration remains
authoritative. For a virtual workspace, the workflow selects the numerically
highest declared `rust-version` among workspace members, excluding external
dependencies. Missing declarations and malformed version strings fail the
selection instead of silently choosing a compiler. This keeps the compiler
selection aligned with the workspace rather than OS path spelling. The legacy `msrv` input is
optional and ignored while existing callers migrate. `msrv-build-targets` can
provide validated Cargo build groups when a repository deliberately supports
an older compiler for its public libraries than for optional or unpublished
workspace crates. Its JSON specifies only package names, feature lists, and
build flags, not shell commands. The check still installs the root package's
declared `rust-version`. `module-e2e-toolchain` defaults to `declared`; set it
to `stable` for the latest stable compiler, or to an exact `X.Y.Z` release such
as `1.88.0` when it needs a reproducible compiler newer than the public library
MSRV. A caller is ready to become a required-check ruleset
target only after every supplied command succeeds on its target runners.

## Release callers

Release callers use `module-release.yml` with the existing release tag and
version, the module cdylib package name, extra package files, the distro toggle,
and the crates.io toggle/package. The shared pipeline builds and verifies the
same 11 native targets in every repository. With distro builds enabled, it also
builds Fedora 43/44 and Arch on x86_64 and arm64, for 17 archives total.

The per-repository scripts implement this interface:

- `scripts/build-module.sh` and `scripts/build-module.ps1` accept `--crate`,
  `--version`, `--target`, `--host`, `--extra-files-json`, and `--output-dir`
  (PowerShell uses `-Crate`, `-Version`, `-Target`, `-HostKey`,
  `-ExtraFilesJson`, and `-OutputDir`). They emit exactly one archive named
  `<crate>-<version>-<host>.tar.gz` or `.zip`, containing the library and its
  `modules.toml` digest.
- `scripts/verify-module.sh` and `scripts/verify-module.ps1` accept `--archive`
  / `-Archive` and load the artifact through TinyBus, exercising the module's
  members.
- `scripts/test-distro.sh` accepts the image followed by the same build inputs;
  it builds and verifies inside that distro image and writes the same archive
  into the output directory.

The release workflow refuses to publish unless it collected exactly 11 native
archives, or all 17 archives when distro builds are enabled. It creates
`checksum.toml` with TinyBus and creates the release once; it does not update an
existing release. Each caller repository must have GitHub immutable releases
enabled; GitHub enforces immutability on publication. Debian and Ubuntu are
represented by the Ubuntu 22.04/24.04 native builds, which already exercise
their LTS glibc baselines. Alpine/musl is not included because TinyBus currently
selects no module artifact for musl hosts. FreeBSD is outside the shipped
Windows/macOS/Linux product set.

When crates.io publishing is enabled, the workflow first dry-runs the package
from the tag, then publishes it after the GitHub release is created. A failed
publish can be retried safely: the workflow recognizes an already-published
crate version and skips it.

Do not rename or remove a required job in the shared workflow without updating
the organization ruleset and the shared drift check in the same change.

## Version changes and SDK releases

Version changes land through a PR before a vX.Y.Z tag is created at the merged
commit. Module release callers accept an existing tag; they never push a bump
commit to main. The shared pipeline verifies that the tagged commit is an
ancestor of main before building.

TinyBus owns the loader/runtime SDK and has no loadable cdylib. It calls the
shared sdk-release.yml to publish a source archive and checksum.toml. Native
module archives and module-load verification are not applicable to that SDK;
its three-platform loader fixture tests remain required CI checks.

## Drift detection

The shared repository's CI runs offline regression tests on every PR. On every
push, manual dispatch, and daily schedule, the module-drift job reads the public
main workflows and active rulesets of all 13 upstream repositories. API errors
fail the job rather than silently skipping a repository. It checks canonical
callers pinned to commit SHAs, all 17 release targets (with the documented
TinyBus SDK exception), the 13 Actions check contexts, strict up-to-date main
protection, required PRs and resolved review threads, deletion/force-push
protection. GitHub hides bypass actors from the default CI token; the audit
prints that limitation. With administrator credentials locally, it additionally
checks administrator bypass on every active branch ruleset. Visible bypass
metadata that violates the contract always fails.

Run locally with Python and PyYAML 6.0.3:

```sh
python3 scripts/test-module-drift.py
GH_TOKEN="$(gh auth token)" python3 scripts/check-module-drift.py
```

This verifies the workflow and ruleset contract. Each module remains responsible
for the behavior and completeness of its scenario and module member tests.

Documented supplemental jobs remain allowed: TinyWallet dependency boundaries,
TinyComputer published-artifact verification, and TinyDocs source packaging.
They supplement the shared checks and release rather than replacing them.
