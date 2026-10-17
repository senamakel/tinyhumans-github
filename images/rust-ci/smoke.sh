#!/usr/bin/env bash
# Build-time checks for the tools and native libraries used by Rust/OpenHuman CI.
set -euo pipefail

rustc +stable --version
rustc "+${RUST_MSRV}" --version
rustc "+${RUST_OPENHUMAN}" --version
cargo +stable clippy --version
cargo +stable fmt --version
cargo "+${RUST_OPENHUMAN}" clippy --version
cargo "+${RUST_OPENHUMAN}" fmt --version
cargo llvm-cov --version
cargo deny --version
cargo nextest --version
tinymold --version
sccache --version
mongod --version | head -1
mongosh --version
mold --version
jq --version
node --version
pnpm --version
python3 -c 'import tomli'
aws --version
ssh -V
slirp4netns --version
iptables --version
command -v newuidmap
command -v newgidmap
patchelf --version
tauri-driver --help
WebKitWebDriver --help

# Compile and link using the headers and libraries needed by Tauri, audio,
# input and tray support, then initialize GTK in a real headless display.
check_dir="${CARGO_HOME}/target/rust-ci-smoke"
mkdir -p "$check_dir"
trap 'rm -rf "$check_dir"' EXIT

# Cargo's linker setting must survive both a relocated CARGO_HOME (EX63)
# and coverage RUSTFLAGS. Verify the linker recorded in real ELF binaries,
# including the minimum and OpenHuman toolchains, rather than just its version.
: "${CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER:?mold must be the default Cargo linker}"
mkdir -p "$check_dir/rust/src" "$check_dir/cargo-home"
cat > "$check_dir/rust/Cargo.toml" <<'TOML'
[package]
name = "rust-ci-linker-smoke"
version = "0.0.0"
edition = "2021"
[workspace]
TOML
printf 'fn main() { println!("mold smoke passed"); }\n' > "$check_dir/rust/src/main.rs"
for toolchain in stable "$RUST_MSRV" "$RUST_OPENHUMAN"; do
  for flags in '' '-C instrument-coverage'; do
    CARGO_HOME="$check_dir/cargo-home" RUSTFLAGS="$flags" \
      cargo "+$toolchain" build --manifest-path "$check_dir/rust/Cargo.toml"
    readelf -p .comment "$check_dir/rust/target/debug/rust-ci-linker-smoke" | grep -q mold
    LLVM_PROFILE_FILE="$check_dir/profile-%p.profraw" "$check_dir/rust/target/debug/rust-ci-linker-smoke"
  done
done

cat > "$check_dir/desktop.c" <<'C'
#include <gtk/gtk.h>
#include <webkit2/webkit2.h>
#include <libappindicator/app-indicator.h>
#include <librsvg/rsvg.h>
#include <alsa/asoundlib.h>
#include <X11/extensions/XTest.h>
#include <libevdev/libevdev.h>
#include <xdo.h>
int main(int argc, char **argv) {
    if (!gtk_init_check(&argc, &argv)) return 1;
    return webkit_get_major_version() < 2 || snd_asoundlib_version() == NULL;
}
C
# pkg-config emits separate compiler/linker arguments intentionally.
# shellcheck disable=SC2046
cc "$check_dir/desktop.c" -o "$check_dir/desktop" -fuse-ld=mold \
    $(pkg-config --cflags --libs gtk+-3.0 webkit2gtk-4.1 appindicator3-0.1 librsvg-2.0 alsa xtst x11 libevdev) -lxdo
xvfb-run -a dbus-run-session -- "$check_dir/desktop"
