# Reviewed module epic release design

## Scope

This is a temporary release admission path for OpenHuman epic 8056. It permits
only the canonical module repositories and package identities below:

| Repository | Module package | CI workflow ID |
| --- | --- | ---: |
| `tinyhumansai/tinyconnectors` | `tinyconnectors` | `345777017` |
| `tinyhumansai/tinybox` | `tinybox` | `334144667` |
| `tinyhumansai/tinyjuice` | `tinyjuice` | `307270985` |
| `tinyhumansai/tinywallet` | `tinywallet-module` | `331024528` |
| `tinyhumansai/tinymcp` | `tinymcp` | `339480400` |
| `tinyhumansai/tinychannels` | `tinychannels-module` | `307289287` |
| `tinyhumansai/tinydocs` | `tinydocs-module` | `331024957` |
| `tinyhumansai/tinyvoice` | `tinyvoice-module` | `333928426` |

The map is compiled into the verifier. Caller inputs cannot choose a
repository, package, CI workflow ID, required check profile, epic branch, or
trusted workflow revision. The release tag must be `v<version>` at the
positive `reviewed-pr` merge commit.

## Admission and execution boundary

The new `module-reviewed-epic-preflight` composite action is independent of the
existing SDK validator and workflow. Its read-only GitHub API preflight checks
the canonical repository, immutable tag target, protected `main` anchor, and
the complete first-parent history between that anchor and the tag. Every
intervening commit must be a two-parent merge for exactly one merged PR into
`epic/8056-modules-wiring`; the merge's second parent must be the PR's final
head. Every such PR must have no effective changes-requested review or
unresolved review thread.

For each PR, preflight proves all 13 trusted `module-ci` checks succeeded on
the exact final head using the canonical repository's `ci.yml` workflow,
latest run attempt, required workflow ID, and Actions check app. It also proves
the trusted `module-ci.yml` pin and the fmt job's checkout of the synthetic PR
merge has the exact ordered parents and tree of the eventual canonical merge.
Pagination, associations, run/job IDs, and downloaded log inputs are bounded
and fail closed. History is fetched into a bare Git repository; the preflight
never checks out or executes tagged code.

Only after admission does the new workflow run module source. Every
source-executing job (metadata validation, native builds, distro builds, and
asset assembly/checksum generation, plus the TinyDocs source-assets job) must
directly depend on successful preflight, check out its emitted source SHA with
`persist-credentials: false`, and use no API token. Both build matrices are
fixed: all 11 native artifacts and all 6 distro artifacts. The module package
verification remains enabled.
Assembly requires successful preflight, metadata validation, native jobs, and
distro jobs; it cannot turn a skipped or failed prerequisite into success.

The publish job alone receives `contents: write`. It downloads assembled
artifacts, invokes the pinned preflight action in tag-only mode immediately
before publishing, verifies the exact artifact set, checksums, and immutable
release retry contents, and executes no module source. There is no crates.io
path or registry secret.

The ordinary `module-release.yml` and all existing SDK workflow/action files
remain byte-for-byte unchanged.

TinyDocs is the only profile with a source bundle. Its source-assets job runs
after preflight and metadata validation, checks out the admitted SHA, packages
only `tinydocs-bus`, and archives the checked-out `vendor/tinybus` gitlink.
Assembly accepts exactly those two flat files, rejects symlinks, extra files,
and collisions, and adds them to the same uploaded release-assets artifact
before checksum generation. The module archive count remains 17, selected
only by the profile stem and version. `checksum.toml` records all 17 module
archives and both TinyDocs source files; the manifest itself is a separate
release asset. The immutable release retry comparison covers the complete
assembled asset set, including the two source files and manifest.

TinyVoice uses only its compiled-in nested manifest
`crates/tinyvoice-module/Cargo.toml` and the Ubuntu native build dependency
list `libasound2-dev libx11-dev libxtst-dev libxi-dev`. The six Fedora/Arch
builds continue to run TinyVoice's pinned `scripts/test-distro.sh`, whose
`scripts/install-distro-packages.sh` installs the corresponding distro-native
audio and X11 packages. The caller cannot supply either the manifest or a
package list.

## Files and ownership

- `.github/workflows/module-reviewed-epic-release.yml`: temporary reusable
  module build-and-publish workflow.
- `.github/actions/module-reviewed-epic-preflight/`: standalone admission
  action, verifier, and its shared historical CI checkout-proof helper.
- `scripts/test-module-reviewed-epic-release.py` and focused fixture module:
  offline negative and positive verifier/workflow tests.
- `docs/module-ci-contract.md`: document the caller contract and removal
  condition.

No module repository, Cargo manifest, or Cargo source is in scope.

## Test-first sequence

1. Add offline fixtures and workflow assertions for all six profiles and
   rejection of unlisted repos/packages/workflow IDs, wrong epic bases, bad
   merge ancestry, direct pushes, false PR associations, failed/missing or
   stale CI attempts, incorrect workflow/check app/pin, incomplete pagination,
   unresolved review threads, effective changes-requested reviews, synthetic
   merge parent/tree mismatches, and moved release tags.
2. Add static workflow assertions for direct successful-preflight dependencies
   on every source-executing job, exact verified-SHA checkout, no source
   checkout in publish, publish-only write permission, fixed 17-target build,
   no registry inputs/secrets, and unchanged legacy SDK/module files. Run the
   focused tests and record the expected failure before implementing.
3. Implement the isolated action and workflow until the focused tests pass;
   run the existing SDK and module workflow contract tests plus actionlint.
4. Freeze the action source in an immutable commit, pin the reusable workflow
   to that full SHA, and verify the pinned action tree exactly matches the
   committed source. Re-run focused tests and actionlint.

## Temporary-path removal

Before epic 8056's final rollup PR reaches canonical `main`, remove the
temporary caller workflow, action, fixtures/tests, and this temporary contract
section. After the epic branch itself has landed on `main`, release from the
unchanged ordinary `module-release.yml` path. Do not merge `main` as part of
this unit.
