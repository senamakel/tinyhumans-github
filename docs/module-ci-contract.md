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
caller supplies the module's coverage command, module loader suite, feature
suite, and any Ubuntu packages needed to build or test it. The `test` job runs
the default feature set; the feature-test command runs on all three operating
systems. The MSRV job and each module-e2e runner read `rust-version` from the
root `Cargo.toml`, so the compiler version cannot drift from the crate
declaration. The MSRV job reads it through Cargo metadata; the cross-platform
E2E runners also use Cargo metadata and normalize manifest paths across
platforms before selecting the root package. The legacy `msrv` input is
optional and ignored while existing callers migrate. `msrv-build-targets` can
provide validated Cargo build groups when a repository deliberately supports
an older compiler for its public libraries than for optional or unpublished
workspace crates. Its JSON specifies only package names, feature lists, and
build flags, not shell commands. The check still installs the root package's
declared `rust-version`. A caller is ready to become a required-check ruleset
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
the organization ruleset and the drift check in OpenHuman in the same change.
