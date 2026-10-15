# rust_ci image

`ghcr.io/tinyhumansai/rust_ci` holds what a Rust workspace's CI job would
otherwise install step by step, so the job starts at its first cargo
command:

| Component | Version |
|---|---|
| Ubuntu | 22.04 (the same base as `openhuman_ci` and the EX63 guest) |
| Rust | `stable` (1.99.1) with rustfmt, clippy, llvm-tools; `1.96` (MSRV); `nightly-2026-10-14` with the Cranelift backend |
| cargo-llvm-cov, cargo-deny | 0.9.1, 0.20.2 |
| tinymold | 0.2.0 |
| MongoDB server, mongosh | 7.0.45, latest 2.x |
| mold, clang, cmake, libssl-dev, pkg-config, jq, git | Ubuntu's |

Every downloaded binary is checked against a sha256 digest pinned in the
Dockerfile. A change to `images/rust-ci/` is built on its pull request and
pushed when it reaches main, tagged `latest`, `rust-<stable>` and
`sha-<commit>`. Pin `sha-<commit>` in workflows.

## Using it

```yaml
jobs:
  rust:
    runs-on: ubuntu-latest
    container: ghcr.io/tinyhumansai/rust_ci:sha-<commit>
    steps:
      - uses: tinyhumansai/.github/actions/checkout@<sha>
      - run: cargo test --all-features
```

Inside a container job, `services:` containers are reachable by their job
name, but `docker run` is not available. Start MongoDB in the job instead
(`mongod --fork --dbpath ... --logpath ...`). The same goes for the EX63
microVMs, which have no Docker either.

## Cranelift

The nightly carries `rustc-codegen-cranelift-preview`. Cranelift compiles
debug builds faster than LLVM and produces slower code, which is the right
trade for `cargo build` and `cargo test` in CI:

```yaml
env:
  CARGO_PROFILE_DEV_CODEGEN_BACKEND: cranelift
run: cargo +nightly-2026-10-14 -Zcodegen-backend test
```

It has no coverage instrumentation, so `cargo llvm-cov` stays on stable.
Code that panics across an `extern "C"` boundary or uses unusual SIMD
intrinsics can still hit gaps in the backend.

## Bumping

- **Rust.** Raise `RUST_STABLE` to the new stable. The build checks that
  rustup's `stable` is that version, so a stale pin fails the build rather
  than publishing a mislabeled image.
- **Nightly.** Move `RUST_NIGHTLY` to a date whose manifest still ships
  `rustc-codegen-cranelift-preview`.
- **The other tools.** Raise the version and replace its `*_SHA256` with
  the digest of the new release asset.
