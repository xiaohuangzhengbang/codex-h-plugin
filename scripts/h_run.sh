#!/bin/sh
set -eu
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORTABLE_LAUNCHER="$SCRIPT_DIR/../runtime/h_launcher"
CODEX_HOME=${CODEX_HOME:-"$HOME/.codex"}
RUNTIME_ID="portable-20260804095000"
GITHUB_RUNTIME_ROOT="$CODEX_HOME/cache/h/github-runtime/$RUNTIME_ID"
GITHUB_RUNTIME_LAUNCHER="$GITHUB_RUNTIME_ROOT/runtime/h_launcher"
GITHUB_RUNTIME_CORE="$GITHUB_RUNTIME_ROOT/runtime/h_core"
RELEASE_BASE="https://github.com/xiaohuangzhengbang/codex-h-plugin/releases/download/v0.4.2-portable.20260804095000"

if [ -f "$PORTABLE_LAUNCHER" ]; then
  chmod +x "$PORTABLE_LAUNCHER"
  exec "$PORTABLE_LAUNCHER" "$@"
fi

runtime_ready() {
  [ -f "$GITHUB_RUNTIME_LAUNCHER" ] && [ -f "$GITHUB_RUNTIME_CORE" ]
}

start_github_runtime() {
  RUNTIME_SOURCE=$1
  shift
  chmod +x "$GITHUB_RUNTIME_LAUNCHER" "$GITHUB_RUNTIME_CORE"
  xattr -dr com.apple.quarantine "$GITHUB_RUNTIME_ROOT" >/dev/null 2>&1 || true
  export H_BOOTSTRAP_PYTHON_SOURCE="$RUNTIME_SOURCE"
  exec "$GITHUB_RUNTIME_LAUNCHER" "$@"
}

download_github_runtime() {
  case "$(uname -m)" in
    arm64)
      ASSET="H-Codex-Plugin-macOS-Apple-Silicon.zip"
      PACKAGE_ROOT="H-Codex-Plugin-macOS-Apple-Silicon"
      EXPECTED_SHA256="cdeaf22000bc76f0d3cf2e5a4d807cda3c34f93a7011049b7e681870d4eef2bf"
      ;;
    x86_64)
      ASSET="H-Codex-Plugin-macOS-Intel.zip"
      PACKAGE_ROOT="H-Codex-Plugin-macOS-Intel"
      EXPECTED_SHA256="b3b27a2ed7a3c435fc933e840ba4e4743ba2383b2683c6f3d8e3ec127d3bd5e7"
      ;;
    *)
      echo "H bootstrap: unsupported Mac architecture: $(uname -m)" >&2
      return 1
      ;;
  esac

  if [ -n "${H_RUNTIME_PACKAGE_SHA256:-}" ]; then
    EXPECTED_SHA256=$(printf '%s' "$H_RUNTIME_PACKAGE_SHA256" | tr '[:upper:]' '[:lower:]')
  fi

  TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/h-github-runtime.XXXXXX") || return 1
  ARCHIVE="$TMP_ROOT/$ASSET"
  EXTRACT_ROOT="$TMP_ROOT/extracted"
  STAGING_ROOT="$GITHUB_RUNTIME_ROOT.installing.$$"

  if [ -n "${H_RUNTIME_PACKAGE_PATH:-}" ]; then
    if [ ! -f "$H_RUNTIME_PACKAGE_PATH" ] || ! cp "$H_RUNTIME_PACKAGE_PATH" "$ARCHIVE"; then
      echo "H bootstrap: H_RUNTIME_PACKAGE_PATH is invalid." >&2
      rm -rf "$TMP_ROOT"
      return 1
    fi
  else
    if ! command -v curl >/dev/null 2>&1; then
      echo "H bootstrap: curl is unavailable, so the GitHub runtime cannot be downloaded." >&2
      rm -rf "$TMP_ROOT"
      return 1
    fi
    DOWNLOAD_URL=${H_RUNTIME_PACKAGE_URL:-"$RELEASE_BASE/$ASSET"}
    echo "H bootstrap: downloading the verified $(uname -m) runtime from GitHub..." >&2
    if ! curl -fL --retry 3 --connect-timeout 20 "$DOWNLOAD_URL" -o "$ARCHIVE"; then
      rm -rf "$TMP_ROOT"
      return 1
    fi
  fi

  if command -v shasum >/dev/null 2>&1; then
    ACTUAL_SHA256=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
  elif command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SHA256=$(sha256sum "$ARCHIVE" | awk '{print $1}')
  else
    echo "H bootstrap: no SHA-256 tool is available." >&2
    rm -rf "$TMP_ROOT"
    return 1
  fi
  ACTUAL_SHA256=$(printf '%s' "$ACTUAL_SHA256" | tr '[:upper:]' '[:lower:]')
  if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
    echo "H bootstrap: downloaded runtime failed SHA-256 verification." >&2
    rm -rf "$TMP_ROOT"
    return 1
  fi

  mkdir -p "$EXTRACT_ROOT"
  if command -v ditto >/dev/null 2>&1; then
    if ! ditto -x -k "$ARCHIVE" "$EXTRACT_ROOT"; then
      rm -rf "$TMP_ROOT"
      return 1
    fi
  elif command -v unzip >/dev/null 2>&1; then
    if ! unzip -q "$ARCHIVE" -d "$EXTRACT_ROOT"; then
      rm -rf "$TMP_ROOT"
      return 1
    fi
  else
    echo "H bootstrap: no ZIP extractor is available." >&2
    rm -rf "$TMP_ROOT"
    return 1
  fi

  PAYLOAD="$EXTRACT_ROOT/$PACKAGE_ROOT/payload"
  if [ ! -f "$PAYLOAD/runtime/h_launcher" ] || [ ! -f "$PAYLOAD/runtime/h_core" ]; then
    echo "H bootstrap: downloaded archive is missing the H runtime." >&2
    rm -rf "$TMP_ROOT"
    return 1
  fi

  mkdir -p "$(dirname "$GITHUB_RUNTIME_ROOT")"
  rm -rf "$STAGING_ROOT"
  if ! cp -R "$PAYLOAD" "$STAGING_ROOT"; then
    rm -rf "$TMP_ROOT" "$STAGING_ROOT"
    return 1
  fi
  chmod +x "$STAGING_ROOT/runtime/h_launcher" "$STAGING_ROOT/runtime/h_core"
  xattr -dr com.apple.quarantine "$STAGING_ROOT" >/dev/null 2>&1 || true

  if ! runtime_ready; then
    rm -rf "$GITHUB_RUNTIME_ROOT"
    if ! mv "$STAGING_ROOT" "$GITHUB_RUNTIME_ROOT"; then
      if ! runtime_ready; then
        rm -rf "$TMP_ROOT" "$STAGING_ROOT"
        return 1
      fi
    fi
  fi

  rm -rf "$TMP_ROOT" "$STAGING_ROOT"
  runtime_ready
}

if runtime_ready; then
  start_github_runtime "github-runtime-cache" "$@"
fi

if download_github_runtime; then
  start_github_runtime "github-runtime-download" "$@"
fi
echo "H bootstrap: GitHub runtime download failed; trying a Python fallback." >&2

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

for candidate in \
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python" \
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python3" \
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python"
do
  if [ -x "$candidate" ] && python_supported "$candidate"; then
    export H_BOOTSTRAP_PYTHON_SOURCE=codex-bundled
    exec "$candidate" "$SCRIPT_DIR/h_run.py" "$@"
  fi
done

for candidate in "$HOME"/.cache/codex-runtimes/*/dependencies/python/bin/python3 "$HOME"/.cache/codex-runtimes/*/dependencies/python/bin/python
do
  if [ -x "$candidate" ] && python_supported "$candidate"; then
    export H_BOOTSTRAP_PYTHON_SOURCE=codex-bundled-discovered
    exec "$candidate" "$SCRIPT_DIR/h_run.py" "$@"
  fi
done

if command -v python3 >/dev/null 2>&1 && python_supported "$(command -v python3)"; then
  export H_BOOTSTRAP_PYTHON_SOURCE=system-path
  exec "$(command -v python3)" "$SCRIPT_DIR/h_run.py" "$@"
fi

if command -v python >/dev/null 2>&1 && python_supported "$(command -v python)"; then
  export H_BOOTSTRAP_PYTHON_SOURCE=system-path
  exec "$(command -v python)" "$SCRIPT_DIR/h_run.py" "$@"
fi

BREW=""
if command -v brew >/dev/null 2>&1; then
  BREW=$(command -v brew)
elif [ -x /opt/homebrew/bin/brew ]; then
  BREW=/opt/homebrew/bin/brew
elif [ -x /usr/local/bin/brew ]; then
  BREW=/usr/local/bin/brew
fi

if [ -n "$BREW" ]; then
  echo "H bootstrap: GitHub runtime download failed; trying Python 3.12 with Homebrew..." >&2
  "$BREW" list python@3.12 >/dev/null 2>&1 || "$BREW" install python@3.12
  BREW_PREFIX=$("$BREW" --prefix python@3.12)
  BREW_PYTHON="$BREW_PREFIX/bin/python3.12"
  if [ -x "$BREW_PYTHON" ] && python_supported "$BREW_PYTHON"; then
    export H_BOOTSTRAP_PYTHON_SOURCE=homebrew-install
    exec "$BREW_PYTHON" "$SCRIPT_DIR/h_run.py" "$@"
  fi
fi

printf '%s\n' '{"ready":false,"state":"setup-error","error_category":"runtime","display_text":"H \u65e0\u6cd5\u4ece GitHub \u51c6\u5907\u8fd0\u884c\u73af\u5883\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5\uff1b\u5c1a\u672a\u63d0\u4ea4\u4efb\u4f55 Kie \u4efb\u52a1\u3002"}'
exit 0
