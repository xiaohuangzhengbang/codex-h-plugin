#!/bin/sh
set -eu
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORTABLE_LAUNCHER="$SCRIPT_DIR/../runtime/h_launcher"

if [ -f "$PORTABLE_LAUNCHER" ]; then
  chmod +x "$PORTABLE_LAUNCHER"
  exec "$PORTABLE_LAUNCHER" "$@"
fi

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
  echo "H bootstrap: Python was not found; installing Python 3.12 with Homebrew..."
  "$BREW" list python@3.12 >/dev/null 2>&1 || "$BREW" install python@3.12
  BREW_PREFIX=$("$BREW" --prefix python@3.12)
  BREW_PYTHON="$BREW_PREFIX/bin/python3.12"
  if [ -x "$BREW_PYTHON" ] && python_supported "$BREW_PYTHON"; then
    export H_BOOTSTRAP_PYTHON_SOURCE=homebrew-install
    exec "$BREW_PYTHON" "$SCRIPT_DIR/h_run.py" "$@"
  fi
fi

echo "H 未找到可用的 Codex Python，也无法自动安装 Python 3.12。请先修复 Codex Desktop 安装后重新调用 H。" >&2
exit 1
