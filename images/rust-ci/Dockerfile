# ghcr.io/tinyhumansai/rust_ci: the toolbox a Rust workspace's CI job would
# otherwise install step by step. Jobs run in it with `container:`, and
# nothing is downloaded before the first cargo command.
#
# Downloaded tool archives are version-pinned and checked against their
# sha256 digests. Bump a version in this file, and the image is rebuilt and
# published from main (see .github/workflows/rust-ci-image.yml).
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

# Build tools and the native libraries the -sys crates link (openssl-sys;
# mongocrypt-sys and others build bundled sources with cc/cmake).
# Desktop, audio/input and headless E2E dependencies mirror OpenHuman's
# .github/Dockerfile; xauth is needed by xvfb-run with --no-install-recommends.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates clang cmake curl git gnupg jq \
        libclang-dev libssl-dev mold pkg-config python3 python3-tomli unzip xz-utils zstd \
        libgtk-3-dev libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf \
        libasound2-dev libxdo-dev libxtst-dev libx11-dev libevdev-dev \
        xvfb xauth at-spi2-core dbus-x11 webkit2gtk-driver \
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
# and the components clippy, fmt and cargo-llvm-cov need. Both are installed
# under the names workflows ask rustup for (`stable` and `1.96`), so
# dtolnay/rust-toolchain finds them instead of downloading them again.
ARG RUST_STABLE=1.99.1
ARG RUST_MSRV=1.96
# OpenHuman's rust-toolchain.toml selects this exact name.
ARG RUST_OPENHUMAN=1.96.1
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path \
        --profile minimal --default-toolchain none \
    && rustup toolchain install stable --profile minimal \
        -c rustfmt -c clippy -c llvm-tools-preview \
    && test "$(rustc +stable --version | cut -d' ' -f2)" = "${RUST_STABLE}" \
    && rustup toolchain install "${RUST_MSRV}" --profile minimal \
    && rustup toolchain install "${RUST_OPENHUMAN}" --profile minimal \
        -c rustfmt -c clippy -c llvm-tools-preview \
    && rustup default stable \
    && chmod -R a+w "${RUSTUP_HOME}" "${CARGO_HOME}"

# Cargo tools, as release binaries checked against pinned digests.
ARG CARGO_LLVM_COV_VERSION=0.9.1
ARG CARGO_LLVM_COV_SHA256=b3f68e625481fed9b16444174f3fa5ebcdbde4a1878803a35eabe2dcefcdc41a
ARG CARGO_DENY_VERSION=0.20.2
ARG CARGO_DENY_SHA256=9f12ed4c49936e09b48bf862b595cde2fe64fcbd9d74dfacac6131ca824c8d5f
ARG CARGO_NEXTEST_VERSION=0.9.148
ARG CARGO_NEXTEST_SHA256=223ba936714cc861a9cdedad5a8eb664dfdd69d6fbdf6cea6aa8184f523290dc
ARG SCCACHE_VERSION=0.18.0
ARG SCCACHE_SHA256=45f1447fbe231e3037bde351ef70677dd212216c8d62ae7ca409fecc4d6acc89
ARG TINYMOLD_VERSION=0.3.0
ARG TINYMOLD_SHA256=3268dc5ef2f9ab75f5a36fde29142e289a2a9e33440fc788802da99f1be41193
RUN set -eu; dl="$(mktemp -d)"; \
    fetch() { curl -fsSL --retry 3 -o "${dl}/$1" "$2" && echo "$3  ${dl}/$1" | sha256sum -c --quiet -; }; \
    fetch llvm-cov.tgz "https://github.com/taiki-e/cargo-llvm-cov/releases/download/v${CARGO_LLVM_COV_VERSION}/cargo-llvm-cov-x86_64-unknown-linux-gnu.tar.gz" "${CARGO_LLVM_COV_SHA256}"; \
    tar -xzf "${dl}/llvm-cov.tgz" -C /usr/local/bin cargo-llvm-cov; \
    fetch deny.tgz "https://github.com/EmbarkStudios/cargo-deny/releases/download/${CARGO_DENY_VERSION}/cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl.tar.gz" "${CARGO_DENY_SHA256}"; \
    tar -xzf "${dl}/deny.tgz" -C /usr/local/bin --strip-components=1 "cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl/cargo-deny"; \
    fetch nextest.tgz "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-${CARGO_NEXTEST_VERSION}/cargo-nextest-${CARGO_NEXTEST_VERSION}-x86_64-unknown-linux-gnu.tar.gz" "${CARGO_NEXTEST_SHA256}"; \
    tar -xzf "${dl}/nextest.tgz" -C /usr/local/bin cargo-nextest; \
    fetch sccache.tgz "https://github.com/mozilla/sccache/releases/download/v${SCCACHE_VERSION}/sccache-v${SCCACHE_VERSION}-x86_64-unknown-linux-musl.tar.gz" "${SCCACHE_SHA256}"; \
    tar -xzf "${dl}/sccache.tgz" -C /usr/local/bin --strip-components=1 "sccache-v${SCCACHE_VERSION}-x86_64-unknown-linux-musl/sccache"; \
    fetch tinymold.tgz "https://github.com/tinyhumansai/tinymold/releases/download/v${TINYMOLD_VERSION}/tinymold-${TINYMOLD_VERSION}-x86_64-unknown-linux-gnu.tar.gz" "${TINYMOLD_SHA256}"; \
    mkdir "${dl}/tm"; tar -xzf "${dl}/tinymold.tgz" -C "${dl}/tm"; \
    install -m 0755 "$(find "${dl}/tm" -type f -name tinymold | head -n1)" /usr/local/bin/tinymold; \
    rm -rf "${dl}"

# Node 24 and OpenHuman's package manager, available before pnpm install.
ARG NODE_VERSION=24.22.0
ARG NODE_SHA256=cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008
ARG PNPM_VERSION=10.10.0
RUN set -eu; dl="$(mktemp -d)"; \
    curl -fsSL --retry 3 -o "${dl}/node.tar.xz" "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    echo "${NODE_SHA256}  ${dl}/node.tar.xz" | sha256sum -c --quiet -; \
    tar -xJf "${dl}/node.tar.xz" -C /usr/local --strip-components=1; \
    rm -rf "${dl}"; \
    npm install --global "pnpm@${PNPM_VERSION}"; \
    npm cache clean --force

# Keep OpenHuman's tauri-driver version; build using its published lockfile.
ARG TAURI_DRIVER_VERSION=2.0.5
RUN cargo +stable install tauri-driver --version "=${TAURI_DRIVER_VERSION}" --locked \
        --root /usr/local --target-dir /usr/local/cargo/target/tauri-driver \
    && rm -rf /usr/local/cargo/target/tauri-driver

# Fail the image build when a tool, native development library or headless
# desktop dependency is missing, rather than discovering it in a CI job.
COPY smoke.sh /usr/local/share/rust-ci/smoke.sh
RUN bash /usr/local/share/rust-ci/smoke.sh
