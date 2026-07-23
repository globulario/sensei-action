#!/usr/bin/env bash
set -euo pipefail

ref="${1:-v1.1.0}"
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

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$bin_dir" >> "$GITHUB_PATH"
else
  export PATH="$bin_dir:$PATH"
fi
