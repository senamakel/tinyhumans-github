# ghcr.io/tinyhumansai/rust_ci: the toolbox a Rust workspace's CI job would
# otherwise install step by step. Jobs run in it with `container:`, and
# nothing is downloaded before the first cargo command.
#
# Every version is pinned here, and every binary is checked against its
# sha256 digest. Bump a version in this file, and the image is rebuilt and
# published from main (see .github/workflows/rust-ci-image.yml).
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

# Build tools and the native libraries the -sys crates link (openssl-sys;
# mongocrypt-sys and others build bundled sources with cc/cmake).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates clang cmake curl git gnupg jq \
        libclang-dev libssl-dev mold pkg-config python3 unzip xz-utils zstd \
    && rm -rf /var/lib/apt/lists/*

# MongoDB 7.0 and mongosh, for tests that need a real server
# (`mongod --fork`, replica sets with `rs.initiate`): the runner's service
# containers and `docker run` are not available inside a container job.
ARG MONGODB_VERSION=7.0.45
RUN curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
        | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg \
    && gpg --no-default-keyring --keyring /usr/share/keyrings/mongodb-server-7.0.gpg \
        --list-keys --with-colons | grep -q '^fpr:::::::::E58830201F7DD82CD808AA84160D26BB1785BA38:' \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
        > /etc/apt/sources.list.d/mongodb-org-7.0.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        "mongodb-org-server=${MONGODB_VERSION}" mongodb-mongosh \
    && rm -rf /var/lib/apt/lists/*

# Rust: the stable release CI builds with, the MSRV it is checked against,
# a nightly with Cranelift, and the components clippy, fmt and cargo-llvm-cov need. Both are installed
# under the names workflows ask rustup for (`stable` and `1.96`), so
# dtolnay/rust-toolchain finds them instead of downloading them again.
ARG RUST_STABLE=1.99.1
ARG RUST_MSRV=1.96
# A dated nightly with the Cranelift codegen backend, for fast debug builds
# and tests: `cargo +nightly-... -Zcodegen-backend` with
# CARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift. Cranelift has no coverage
# instrumentation, so cargo llvm-cov stays on stable.
ARG RUST_NIGHTLY=nightly-2026-10-14
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path \
        --profile minimal --default-toolchain none \
    && rustup toolchain install stable --profile minimal \
        -c rustfmt -c clippy -c llvm-tools-preview \
    && test "$(rustc +stable --version | cut -d' ' -f2)" = "${RUST_STABLE}" \
    && rustup toolchain install "${RUST_MSRV}" --profile minimal \
    && rustup toolchain install "${RUST_NIGHTLY}" --profile minimal \
        -c rustc-codegen-cranelift-preview -c clippy -c rustfmt \
    && rustup default stable \
    && chmod -R a+w "${RUSTUP_HOME}" "${CARGO_HOME}"

# Cargo tools, as release binaries checked against pinned digests.
ARG CARGO_LLVM_COV_VERSION=0.9.1
ARG CARGO_LLVM_COV_SHA256=b3f68e625481fed9b16444174f3fa5ebcdbde4a1878803a35eabe2dcefcdc41a
ARG CARGO_DENY_VERSION=0.20.2
ARG CARGO_DENY_SHA256=9f12ed4c49936e09b48bf862b595cde2fe64fcbd9d74dfacac6131ca824c8d5f
ARG TINYMOLD_VERSION=0.2.0
ARG TINYMOLD_SHA256=cccb75cdeccf29b3647832c5c7b3d5dc515f32cf07a9aba139e983ffb977fc4d
RUN set -eu; dl="$(mktemp -d)"; \
    fetch() { curl -fsSL --retry 3 -o "${dl}/$1" "$2" && echo "$3  ${dl}/$1" | sha256sum -c --quiet -; }; \
    fetch llvm-cov.tgz "https://github.com/taiki-e/cargo-llvm-cov/releases/download/v${CARGO_LLVM_COV_VERSION}/cargo-llvm-cov-x86_64-unknown-linux-gnu.tar.gz" "${CARGO_LLVM_COV_SHA256}"; \
    tar -xzf "${dl}/llvm-cov.tgz" -C /usr/local/bin cargo-llvm-cov; \
    fetch deny.tgz "https://github.com/EmbarkStudios/cargo-deny/releases/download/${CARGO_DENY_VERSION}/cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl.tar.gz" "${CARGO_DENY_SHA256}"; \
    tar -xzf "${dl}/deny.tgz" -C /usr/local/bin --strip-components=1 "cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl/cargo-deny"; \
    fetch tinymold.tgz "https://github.com/tinyhumansai/tinymold/releases/download/v${TINYMOLD_VERSION}/tinymold-${TINYMOLD_VERSION}-x86_64-unknown-linux-gnu.tar.gz" "${TINYMOLD_SHA256}"; \
    mkdir "${dl}/tm"; tar -xzf "${dl}/tinymold.tgz" -C "${dl}/tm"; \
    install -m 0755 "$(find "${dl}/tm" -type f -name tinymold | head -n1)" /usr/local/bin/tinymold; \
    rm -rf "${dl}"

# Fail the build, not a CI job, when something above is missing.
RUN rustc +stable --version && rustc "+${RUST_MSRV}" --version && cargo clippy --version \
    && rustc "+${RUST_NIGHTLY}" -Zcodegen-backend=cranelift --version \
    && cargo fmt --version && cargo llvm-cov --version && cargo deny --version \
    && tinymold --version && mongod --version | head -1 && mongosh --version \
    && mold --version && jq --version
