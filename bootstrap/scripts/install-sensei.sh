#!/usr/bin/env bash
set -euo pipefail

ref="${1:-v1.6.0}"
bin_dir="${RUNNER_TEMP:-/tmp}/sensei-bin"
mkdir -p "$bin_dir"

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  MINGW*|MSYS*|CYGWIN*) os=windows ;;
  *) os=linux ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) arch=amd64 ;;
esac
platform="${os}-${arch}"
release="https://github.com/globulario/sensei/releases/download/${ref}"
archive="${RUNNER_TEMP:-/tmp}/sensei.tgz"

if curl -fsSL -o "$archive" "${release}/sensei-${platform}.tar.gz"; then
  (
    cd "${RUNNER_TEMP:-/tmp}"
    tar xzf "$(basename "$archive")"
  )
  cp "${RUNNER_TEMP:-/tmp}/sensei-${platform}/bin/"* "$bin_dir/"
  chmod +x "$bin_dir/"*
  echo "Using prebuilt Sensei bundle ${ref} for ${platform}."
else
  echo "No prebuilt Sensei bundle for ${ref}/${platform}; building from source."
  command -v go >/dev/null 2>&1 || {
    echo "::error::Go is required for the Sensei source-build fallback."
    exit 1
  }
  src="${RUNNER_TEMP:-/tmp}/sensei-src"
  rm -rf "$src"
  git clone --depth 1 --branch "$ref" https://github.com/globulario/sensei "$src"
  (
    cd "$src"
    go build -o "$bin_dir/sensei" ./cmd/awg
  )
fi

# Sensei v1.1.0 used `bootstrap --repo`; current Sensei prefers `--path` and
# retains `--repo` as a compatibility alias. Normalize the modern Action
# contract to the older flag so one pinned workflow works with both versions.
if [[ -f "$bin_dir/sensei" ]]; then
  mv "$bin_dir/sensei" "$bin_dir/sensei-real"
  cat > "$bin_dir/sensei" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
translated=()
for argument in "$@"; do
  if [[ "$argument" == "--path" ]]; then
    argument="--repo"
  fi
  translated+=("$argument")
done
exec "$script_dir/sensei-real" "${translated[@]}"
WRAPPER
  chmod +x "$bin_dir/sensei" "$bin_dir/sensei-real"
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$bin_dir" >> "$GITHUB_PATH"
else
  export PATH="$bin_dir:$PATH"
fi
