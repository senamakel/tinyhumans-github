#!/usr/bin/env bash
# Conflicting rustc linker hints must not override the image's mold linker.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
cat > "$fixture/clang" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$MOLD_TEST_ARGS"
SH
chmod +x "$fixture/clang"
PATH="$fixture:$PATH" MOLD_TEST_ARGS="$fixture/args" \
  bash "$root/mold-linker" -fuse-ld=lld 'object with spaces.o'
printf '%s\n' '-fuse-ld=lld' 'object with spaces.o' '--ld-path=/opt/mold/bin/mold' > "$fixture/expected"
diff -u "$fixture/expected" "$fixture/args"
