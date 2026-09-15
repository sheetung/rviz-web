#!/usr/bin/env bash
# Version pins are shared by installation and normal startup.
configure_frontend_runtime() {
  FRONTEND_NODE_VERSION="$(cat "$PROJECT_ROOT/.node-version")"
  FRONTEND_NPM_VERSION="$(cat "$PROJECT_ROOT/.npm-version")"
  FRONTEND_RUNTIME_DIR="$PROJECT_ROOT/.cache/node-v$FRONTEND_NODE_VERSION"
  if [[ -d "$FRONTEND_RUNTIME_DIR/bin" ]]; then
    export PATH="$FRONTEND_RUNTIME_DIR/bin:$PATH"
    hash -r
  fi
}

check_frontend_runtime() {
  [[ "$(node --version 2>/dev/null)" == "v$FRONTEND_NODE_VERSION" &&
     "$(npm --version 2>/dev/null)" == "$FRONTEND_NPM_VERSION" ]]
}

ensure_frontend_runtime() {
  configure_frontend_runtime
  check_frontend_runtime && return 0
  echo "[rvizweb] Installing pinned Node.js $FRONTEND_NODE_VERSION / npm $FRONTEND_NPM_VERSION"
  (
    set -e
    local architecture archive staging base_url download_ok=false
    local -a download_urls
    read -r -a download_urls <<< "${NODE_DOWNLOAD_URLS:-https://nodejs.org/dist https://mirrors.tuna.tsinghua.edu.cn/nodejs-release https://npmmirror.com/mirrors/node}"
    [[ "$(uname -s)" == Linux ]] || { echo 'Automatic Node installation requires Linux.' >&2; exit 1; }
    case "$(uname -m)" in
      x86_64) architecture=x64 ;;
      aarch64|arm64) architecture=arm64 ;;
      *) echo 'Unsupported architecture for automatic Node installation.' >&2; exit 1 ;;
    esac
    for tool in curl tar xz sha256sum; do
      command -v "$tool" >/dev/null || { echo "Missing command: $tool" >&2; exit 1; }
    done
    mkdir -p "$PROJECT_ROOT/.cache" || exit 1
    staging="$(mktemp -d "$PROJECT_ROOT/.cache/node-install.XXXXXX")" || exit 1
    trap 'rm -rf -- "$staging"' EXIT
    archive="node-v$FRONTEND_NODE_VERSION-linux-$architecture.tar.xz"
    cd "$staging" || exit 1
    for base_url in "${download_urls[@]}"; do
      [[ "$base_url" == https://* ]] || { echo 'Node download URLs must use HTTPS.' >&2; exit 1; }
      base_url="${base_url%/}/v$FRONTEND_NODE_VERSION"
      echo "[rvizweb] Trying Node source: $base_url"
      if curl --fail --silent --show-error --location --retry 1 --connect-timeout 10 --max-time 30 \
           "$base_url/SHASUMS256.txt" -o SHASUMS256.txt &&
         awk -v archive="$archive" '$2 == archive' SHASUMS256.txt > selected.sha256 &&
         [[ -s selected.sha256 ]] &&
         curl --fail --silent --show-error --location --retry 1 --connect-timeout 10 --max-time 300 \
           "$base_url/$archive" -o "$archive" &&
         sha256sum --check selected.sha256; then
        download_ok=true
        break
      fi
      echo '[rvizweb] Node source failed or checksum did not match; trying next source.' >&2
    done
    [[ "$download_ok" == true ]] || { echo 'All Node download sources failed.' >&2; exit 1; }
    tar -xJf "$archive" --no-same-owner || exit 1
    export PATH="$staging/${archive%.tar.xz}/bin:$PATH"
    hash -r
    check_frontend_runtime || { echo 'Downloaded Node/npm do not match the version pins.' >&2; exit 1; }
    if [[ -e "$FRONTEND_RUNTIME_DIR" ]]; then
      mv "$FRONTEND_RUNTIME_DIR" "$staging/previous" || exit 1
    fi
    mv "${archive%.tar.xz}" "$FRONTEND_RUNTIME_DIR" || exit 1
  ) || { echo 'Pinned Node installation failed; check NODE_DOWNLOAD_URLS in .env and network access, then retry ./install.sh.' >&2; return 1; }
  configure_frontend_runtime
  check_frontend_runtime
}
