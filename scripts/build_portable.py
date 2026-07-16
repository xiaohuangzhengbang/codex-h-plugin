#!/usr/bin/env python3
"""Build a self-contained H package that does not require Python on the target."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_NAMES = {
    "windows-x64": "H-Codex-Plugin-Windows-x64",
    "macos-intel": "H-Codex-Plugin-macOS-Intel",
    "macos-apple-silicon": "H-Codex-Plugin-macOS-Apple-Silicon",
}
PAYLOAD_DIRECTORIES = [".codex-plugin", "assets", "skills"]
PAYLOAD_FILES = ["README.md", "INSTALL.md", "LICENSE", "requirements.txt"]
PAYLOAD_SCRIPTS = ["h_run.py", "h_run.cmd", "h_run.sh", "h_bootstrap.ps1", "kie_video_batch.py"]


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout[-4000:]}")
    return result


def parse_last_json(output: str) -> dict[str, Any]:
    lines = output.strip().splitlines()
    for start in range(len(lines)):
        try:
            value = json.loads("\n".join(lines[start:]))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"No JSON object found in output:\n{output[-2000:]}")


def assert_platform(target: str) -> None:
    machine = platform.machine().lower()
    if target == "windows-x64" and not (os.name == "nt" and machine in {"amd64", "x86_64"}):
        raise RuntimeError(f"windows-x64 must be built on Windows x64, current platform is {sys.platform}/{machine}")
    if target == "macos-intel" and not (sys.platform == "darwin" and machine == "x86_64"):
        raise RuntimeError(f"macos-intel must be built on an Intel Mac, current platform is {sys.platform}/{machine}")
    if target == "macos-apple-silicon" and not (sys.platform == "darwin" and machine == "arm64"):
        raise RuntimeError(f"macos-apple-silicon must be built on Apple Silicon, current platform is {sys.platform}/{machine}")


def copy_payload(payload: Path) -> None:
    payload.mkdir(parents=True)
    for relative in PAYLOAD_DIRECTORIES:
        shutil.copytree(ROOT / relative, payload / relative)
    for relative in PAYLOAD_FILES:
        shutil.copy2(ROOT / relative, payload / relative)
    scripts = payload / "scripts"
    scripts.mkdir()
    for name in PAYLOAD_SCRIPTS:
        shutil.copy2(ROOT / "scripts" / name, scripts / name)


def build_binary(name: str, script: Path, runtime_dir: Path, work_root: Path, *, include_certifi: bool) -> Path:
    (work_root / "specs").mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(runtime_dir),
        "--workpath",
        str(work_root / name),
        "--specpath",
        str(work_root / "specs"),
    ]
    if include_certifi:
        command.extend(["--collect-data", "certifi"])
    command.append(str(script))
    run(command, timeout=1200)
    binary = runtime_dir / (f"{name}.exe" if os.name == "nt" else name)
    if not binary.is_file():
        raise RuntimeError(f"PyInstaller did not create {binary}")
    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | 0o111)
    if sys.platform == "darwin":
        run(["codesign", "--force", "--deep", "--sign", "-", str(binary)], timeout=120)
    return binary


def write_installers(package_root: Path, target: str) -> None:
    instructions = f"""H Codex 插件离线安装包

适用平台：{PLATFORM_NAMES[target]}

这个压缩包已经包含 H 的运行程序和 Python 依赖。目标电脑不需要安装 Python、pip、Homebrew 或 Git。

安装方法：
1. 必须先完整解压整个文件夹，不要只打开压缩包预览。
2. 把解压后的整个文件夹交给 Codex，并让它运行安装文件；也可以自己运行安装文件。
3. Windows 运行 Install-H-Windows.cmd。
4. Mac 运行 Install-H.command；如果系统拦截，右键该文件选择“打开”。
5. 看到“H 安装完成”后，完全退出并重新打开 Codex，再新建任务调用 H。

安装器会注册本地 personal marketplace，不会要求 Codex 识别 GitHub 链接，也不会覆盖其他个人插件。
Kie API Key 仍保存在用户自己的 ~/.codex/secrets/h_kie_api_key.txt，不包含在本压缩包中。
"""
    (package_root / "安装说明.txt").write_text(instructions, encoding="utf-8")
    if target == "windows-x64":
        installer = r"""@echo off
setlocal
chcp 65001 >nul
"%~dp0payload\runtime\h_launcher.exe" install-local
exit /b %errorlevel%
"""
        (package_root / "Install-H-Windows.cmd").write_text(installer, encoding="utf-8")
    else:
        installer = """#!/bin/sh
set -u
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
chmod +x "$ROOT/payload/runtime/h_launcher" "$ROOT/payload/runtime/h_core"
xattr -dr com.apple.quarantine "$ROOT/payload" >/dev/null 2>&1 || true
"$ROOT/payload/runtime/h_launcher" install-local
status=$?
if [ -t 0 ]; then
  printf '\n按回车键关闭...'
  read -r _answer
fi
exit $status
"""
        path = package_root / "Install-H.command"
        path.write_text(installer, encoding="utf-8", newline="\n")
        path.chmod(0o755)


def smoke_test(package_root: Path) -> None:
    runtime = package_root / "payload" / "runtime"
    launcher = runtime / ("h_launcher.exe" if os.name == "nt" else "h_launcher")
    core = runtime / ("h_core.exe" if os.name == "nt" else "h_core")
    core_catalog = parse_last_json(run([str(core), "catalog"], cwd=package_root).stdout)
    if not core_catalog.get("image") or not core_catalog.get("video"):
        raise RuntimeError("Packaged h_core catalog is incomplete.")
    with tempfile.TemporaryDirectory(prefix="h-portable-smoke-") as temp_dir:
        home = Path(temp_dir)
        env = os.environ.copy()
        env["H_INSTALL_HOME"] = str(home)
        env["CODEX_HOME"] = str(home / ".codex")
        install = subprocess.run(
            [str(launcher), "install-local"],
            cwd=str(package_root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=600,
        )
        if install.returncode != 0:
            raise RuntimeError(f"Portable local installation failed:\n{install.stdout[-4000:]}")
        installed = parse_last_json(install.stdout)
        if not installed.get("ready") or not installed.get("portable_runtime"):
            raise RuntimeError(f"Portable local installation returned an invalid result:\n{install.stdout[-4000:]}")
        installed_launcher = home / ".agents" / "plugins" / "plugins" / "h" / "runtime" / launcher.name
        protocol = subprocess.run(
            [str(installed_launcher), "protocol", "batch-image"],
            cwd=str(installed_launcher.parent.parent),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=300,
        )
        payload = parse_last_json(protocol.stdout)
        if protocol.returncode != 0 or not payload.get("ready") or "GPT Image-2" not in payload.get("display_text", ""):
            raise RuntimeError(f"Installed portable H protocol smoke test failed:\n{protocol.stdout[-4000:]}")
        marketplace = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        h_entries = [item for item in marketplace["plugins"] if item.get("name") == "h"]
        if len(h_entries) != 1 or h_entries[0]["policy"]["installation"] != "INSTALLED_BY_DEFAULT":
            raise RuntimeError("Portable installer did not register H as an installed-by-default local plugin.")


def write_zip(package_root: Path, output_dir: Path, package_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{package_name}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_root)
            archive.write(path, (Path(package_name) / relative).as_posix())
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORM_NAMES))
    parser.add_argument("--output-dir", default=str(ROOT / "portable-dist"))
    args = parser.parse_args()
    assert_platform(args.platform)
    package_name = PLATFORM_NAMES[args.platform]
    build_root = ROOT / "build" / "portable" / args.platform
    if build_root.exists():
        shutil.rmtree(build_root)
    package_root = build_root / package_name
    payload = package_root / "payload"
    copy_payload(payload)
    runtime = payload / "runtime"
    runtime.mkdir()
    work_root = build_root / "pyinstaller"
    build_binary("h_core", ROOT / "scripts" / "kie_video_batch.py", runtime, work_root, include_certifi=True)
    build_binary("h_launcher", ROOT / "scripts" / "h_run.py", runtime, work_root, include_certifi=False)
    write_installers(package_root, args.platform)
    info = {
        "name": package_name,
        "platform": args.platform,
        "architecture": platform.machine(),
        "plugin_version": json.loads((payload / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"],
        "requires_python": False,
        "requires_git": False,
        "requires_homebrew": False,
    }
    (package_root / "PACKAGE-INFO.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    smoke_test(package_root)
    destination = write_zip(package_root, Path(args.output_dir), package_name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(json.dumps({"package": str(destination), "sha256": digest, **info}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
