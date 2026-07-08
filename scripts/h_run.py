#!/usr/bin/env python
"""Portable launcher and bootstrap checker for the H plugin.

This file uses only the Python standard library. It creates a plugin-local
virtual environment, installs runtime dependencies from requirements.txt, and
then runs the real H workflow script with the venv Python.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = PLUGIN_ROOT / "requirements.txt"
VENV_DIR = PLUGIN_ROOT / ".h_venv"
MAIN_SCRIPT = PLUGIN_ROOT / "scripts" / "kie_video_batch.py"
READY_FILE = PLUGIN_ROOT / ".h_ready.json"
REQUIRED_IMPORTS = ["requests"]


def print_greeting() -> None:
    greeting = (
        "\u54c8\u55bd\u5c0f\u6768\uff0c\u4f60\u53c8\u5f00\u59cb"
        "\u5de5\u4f5c\u5566\uff0c\u60f3\u4e0d\u60f3\u5c0f\u9ec4\u554a\uff1f"
    )
    print(greeting, flush=True)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_quiet(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print("H bootstrap: creating plugin-local Python environment...", flush=True)
        result = run_quiet([sys.executable, "-m", "venv", str(VENV_DIR)])
        if result.returncode != 0:
            raise SystemExit("H bootstrap failed while creating .h_venv:\n" + result.stdout[-2000:])
    return python


def ensure_dependencies(python: Path) -> None:
    check_code = "; ".join(f"import {name}" for name in REQUIRED_IMPORTS)
    check = run_quiet([str(python), "-c", check_code])
    if check.returncode == 0:
        return
    print("H bootstrap: installing runtime dependencies...", flush=True)
    result = run_quiet([str(python), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)])
    if result.returncode != 0:
        raise SystemExit("H dependency installation failed:\n" + result.stdout[-2000:])


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def key_sources() -> list[str]:
    sources = []
    if os.environ.get("H_KIE_API_KEY"):
        sources.append("H_KIE_API_KEY")
    if os.environ.get("KIE_API_KEY"):
        sources.append("KIE_API_KEY")
    if (Path.home() / ".codex" / "secrets" / "h_kie_api_key.txt").exists():
        sources.append("<home>/.codex/secrets/h_kie_api_key.txt")
    if (PLUGIN_ROOT / ".h_api_key").exists():
        sources.append("plugin-local .h_api_key")
    return sources


def write_ready(python: Path) -> None:
    data = {
        "ready": True,
        "time": int(time.time()),
        "python": str(python),
        "plugin_root": str(PLUGIN_ROOT),
        "requirements": str(REQUIREMENTS),
        "desktop_exists": desktop_dir().exists(),
        "key_sources": key_sources(),
    }
    READY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def doctor() -> int:
    python = ensure_venv()
    ensure_dependencies(python)
    checks = {
        "python": str(python),
        "requirements": REQUIREMENTS.exists(),
        "main_script": MAIN_SCRIPT.exists(),
        "desktop": str(desktop_dir()),
        "desktop_exists": desktop_dir().exists(),
        "kie_key_sources": key_sources(),
    }
    ready = bool(checks["requirements"] and checks["main_script"])
    if ready:
        write_ready(python)
    print(json.dumps({"ready": ready, "checks": checks}, ensure_ascii=False, indent=2), flush=True)
    return 0 if ready else 1


def main(argv: list[str]) -> int:
    print_greeting()
    if argv and argv[0] in {"--doctor", "doctor", "bootstrap", "--bootstrap"}:
        return doctor()
    python = ensure_venv()
    ensure_dependencies(python)
    write_ready(python)
    command = [str(python), str(MAIN_SCRIPT), *argv]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
