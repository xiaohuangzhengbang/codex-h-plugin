#!/usr/bin/env python3
"""Portable launcher and first-use bootstrap for the H plugin."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = PLUGIN_ROOT / "requirements.txt"
MAIN_SCRIPT = PLUGIN_ROOT / "scripts" / "kie_video_batch.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
CACHE_ROOT = CODEX_HOME / "cache" / "h"
USER_KEY_FILE = CODEX_HOME / "secrets" / "h_kie_api_key.txt"
LOCAL_KEY_FILE = PLUGIN_ROOT / ".h_api_key"
REQUIRED_IMPORTS = ["requests"]
MIN_PYTHON = (3, 10)


def print_greeting() -> None:
    greeting = (
        "\u54c8\u55bd\u5c0f\u6768\uff0c\u4f60\u53c8\u5f00\u59cb"
        "\u5de5\u4f5c\u5566\uff0c\u60f3\u4e0d\u60f3\u5c0f\u9ec4\u554a\uff1f"
    )
    print(greeting, flush=True)


def requirements_hash() -> str:
    payload = REQUIREMENTS.read_bytes() if REQUIREMENTS.exists() else b""
    payload += f"|py{sys.version_info.major}.{sys.version_info.minor}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()[:16]


RUNTIME_ID = requirements_hash()
VENV_DIR = CACHE_ROOT / "venvs" / RUNTIME_ID
READY_FILE = CACHE_ROOT / f"ready-{RUNTIME_ID}.json"
DEPENDENCY_MARKER = VENV_DIR / ".h-requirements.sha256"
LOCK_FILE = CACHE_ROOT / "bootstrap.lock"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_quiet(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(command[:3])}\n{output[-1000:]}") from exc


class BootstrapLock:
    def __enter__(self) -> "BootstrapLock":
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 180
        while True:
            try:
                descriptor = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - LOCK_FILE.stat().st_mtime > 900:
                        LOCK_FILE.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("H bootstrap is still locked by another process after 180 seconds.")
                time.sleep(0.25)
                continue
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(f"{os.getpid()} {int(time.time())}\n")
            return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(f"H requires Python 3.10 or newer; current Python is {current}.")


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists():
        return python
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    print("H bootstrap: creating the reusable Python environment...", flush=True)
    result = run_quiet([sys.executable, "-m", "venv", str(VENV_DIR)], timeout=180)
    if result.returncode != 0:
        raise SystemExit("H bootstrap failed while creating its Python environment:\n" + result.stdout[-2000:])
    return python


def dependencies_ready(python: Path) -> bool:
    if not DEPENDENCY_MARKER.exists():
        return False
    if DEPENDENCY_MARKER.read_text(encoding="ascii").strip() != RUNTIME_ID:
        return False
    check_code = "; ".join(f"import {name}" for name in REQUIRED_IMPORTS)
    return run_quiet([str(python), "-c", check_code], timeout=30).returncode == 0


def ensure_dependencies(python: Path) -> None:
    if dependencies_ready(python):
        return
    print("H bootstrap: installing runtime dependencies...", flush=True)
    result = run_quiet(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)],
        timeout=600,
    )
    if result.returncode != 0:
        raise SystemExit("H dependency installation failed:\n" + result.stdout[-2000:])
    DEPENDENCY_MARKER.write_text(RUNTIME_ID, encoding="ascii")


def bootstrap() -> Path:
    ensure_python_version()
    with BootstrapLock():
        python = ensure_venv()
        ensure_dependencies(python)
    return python


def desktop_dir() -> Path:
    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
                if value:
                    return Path(os.path.expandvars(str(value))).expanduser()
        except (OSError, ImportError):
            pass
    return Path.home() / "Desktop"


def desktop_writable() -> bool:
    desktop = desktop_dir()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        probe = desktop / f".h-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return True
    except OSError:
        return False


def key_sources() -> list[str]:
    sources: list[str] = []
    if os.environ.get("H_KIE_API_KEY"):
        sources.append("H_KIE_API_KEY")
    if os.environ.get("KIE_API_KEY"):
        sources.append("KIE_API_KEY")
    if USER_KEY_FILE.exists():
        sources.append("<home>/.codex/secrets/h_kie_api_key.txt")
    if LOCAL_KEY_FILE.exists():
        sources.append("plugin-local .h_api_key")
    return sources


def plugin_version() -> str:
    manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        return "unknown"


def write_ready(python: Path, checks: dict[str, object]) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    data = {
        "ready": True,
        "time": int(time.time()),
        "python": str(python),
        "plugin_root": str(PLUGIN_ROOT),
        "plugin_version": plugin_version(),
        "requirements_hash": RUNTIME_ID,
        "checks": checks,
    }
    READY_FILE.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def parse_last_json(output: str) -> dict[str, object]:
    lines = output.strip().splitlines()
    for start in range(len(lines)):
        candidate = "\n".join(lines[start:])
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def doctor(*, offline: bool = False, forwarded_args: list[str] | None = None) -> int:
    python = bootstrap()
    sources = key_sources()
    forwarded_args = forwarded_args or []
    if "--api-key" in forwarded_args:
        sources = ["--api-key", *sources]
    checks: dict[str, object] = {
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "python_supported": sys.version_info >= MIN_PYTHON,
        "requirements": REQUIREMENTS.exists(),
        "dependencies": dependencies_ready(python),
        "main_script": MAIN_SCRIPT.exists(),
        "desktop": str(desktop_dir()),
        "desktop_writable": desktop_writable(),
        "kie_key_sources": sources,
        "runtime": str(VENV_DIR),
    }
    local_ready = all(
        bool(checks[name])
        for name in ("python_supported", "requirements", "dependencies", "main_script", "desktop_writable")
    ) and (bool(sources) or offline)
    api_ready = offline
    if local_ready and not offline:
        result = run_quiet(
            [str(python), str(MAIN_SCRIPT), "doctor", *forwarded_args],
            cwd=PLUGIN_ROOT,
            timeout=60,
        )
        api_result = parse_last_json(result.stdout)
        checks["kie_api"] = api_result or {"ready": False, "message": result.stdout[-1000:]}
        api_ready = result.returncode == 0 and bool(api_result.get("ready"))
    ready = local_ready and api_ready
    if ready:
        write_ready(python, checks)
    print(json.dumps({"ready": ready, "checks": checks}, ensure_ascii=True, indent=2), flush=True)
    return 0 if ready else 1


def set_key() -> int:
    value = getpass.getpass("Kie API key: ").strip().lstrip("\ufeff")
    value = "".join(ch for ch in value if ch.isprintable() and not ch.isspace())
    if not value:
        raise SystemExit("No Kie API key was entered.")
    USER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_KEY_FILE.write_text(value, encoding="utf-8")
    print(f"Kie API key saved to {USER_KEY_FILE}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    print_greeting()
    if argv and argv[0] == "set-key":
        return set_key()
    if argv and argv[0] in {"bootstrap", "--bootstrap"}:
        return doctor(offline=True)
    if argv and argv[0] in {"--doctor", "doctor"}:
        extra = [value for value in argv[1:] if value != "--offline"]
        return doctor(offline="--offline" in argv[1:], forwarded_args=extra)
    python = bootstrap()
    return subprocess.call([str(python), str(MAIN_SCRIPT), *argv], cwd=str(PLUGIN_ROOT))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
