#!/usr/bin/env python3
"""Portable launcher, first-use bootstrap, and fixed UI protocol for H."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


IS_FROZEN = bool(getattr(sys, "frozen", False))
PLUGIN_ROOT = (
    Path(sys.executable).resolve().parent.parent
    if IS_FROZEN
    else Path(__file__).resolve().parents[1]
)
REQUIREMENTS = PLUGIN_ROOT / "requirements.txt"
MAIN_SCRIPT = PLUGIN_ROOT / "scripts" / "kie_video_batch.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
CACHE_ROOT = CODEX_HOME / "cache" / "h"
USER_KEY_FILE = CODEX_HOME / "secrets" / "h_kie_api_key.txt"
LOCAL_KEY_FILE = PLUGIN_ROOT / ".h_api_key"
REQUIRED_IMPORTS = ["requests"]
MIN_PYTHON = (3, 10)
PROTOCOL_VERSION = "h-fixed-v1"
GREETING = "哈喽小杨，你又开始工作啦，想不想小黄啊？"
MODE_MENU = "请选择处理模式，回复编号即可：\n1. 批处理\n2. 单处理"


def configure_utf8_output() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def print_json(value: dict[str, Any]) -> None:
    configure_utf8_output()
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def requirements_hash() -> str:
    payload = REQUIREMENTS.read_bytes() if REQUIREMENTS.exists() else b""
    payload += f"|py{sys.version_info.major}.{sys.version_info.minor}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()[:16]


RUNTIME_ID = requirements_hash()
VENV_DIR = CACHE_ROOT / "venvs" / RUNTIME_ID
READY_FILE = CACHE_ROOT / f"ready-{RUNTIME_ID}.json"
DEPENDENCY_MARKER = VENV_DIR / ".h-requirements.sha256"
LOCK_FILE = CACHE_ROOT / "bootstrap.lock"


def packaged_core_path() -> Path | None:
    executable_name = "h_core.exe" if os.name == "nt" else "h_core"
    candidates = []
    if IS_FROZEN:
        candidates.append(Path(sys.executable).resolve().parent / executable_name)
    candidates.append(PLUGIN_ROOT / "runtime" / executable_name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class BootstrapReport:
    python: str
    environment_created: bool
    dependencies_installed: bool
    missing_before: list[str]
    marker_was_current: bool
    runtime_source: str


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_quiet(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 600,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if env_overrides:
        env.update(env_overrides)
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        raise RuntimeError(
            f"Command timed out after {timeout}s: {' '.join(command[:3])}\n{str(output)[-1000:]}"
        ) from exc


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
        raise RuntimeError(f"H requires Python 3.10 or newer; current Python is {current}.")


def python_works(python: Path) -> bool:
    if not python.exists():
        return False
    result = run_quiet(
        [str(python), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
        timeout=30,
    )
    return result.returncode == 0


def ensure_venv() -> tuple[Path, bool]:
    python = venv_python()
    if python_works(python):
        return python, False
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    print("H bootstrap: creating the reusable Python environment...", flush=True)
    command = [sys.executable, "-m", "venv"]
    if VENV_DIR.exists():
        command.append("--clear")
    command.append(str(VENV_DIR))
    result = run_quiet(command, timeout=180)
    if result.returncode != 0 or not python_works(python):
        raise RuntimeError("H bootstrap failed while creating its Python environment:\n" + result.stdout[-2000:])
    return python, True


def ensure_pip(python: Path) -> None:
    if run_quiet([str(python), "-m", "pip", "--version"], timeout=30).returncode == 0:
        return
    result = run_quiet([str(python), "-m", "ensurepip", "--upgrade"], timeout=180)
    if result.returncode != 0:
        raise RuntimeError("H could not prepare pip in its private environment:\n" + result.stdout[-2000:])


def dependency_marker_current() -> bool:
    try:
        return DEPENDENCY_MARKER.read_text(encoding="ascii").strip() == RUNTIME_ID
    except OSError:
        return False


def missing_imports(python: Path, names: list[str] | None = None) -> list[str]:
    names = names or REQUIRED_IMPORTS
    code = (
        "import importlib.util,json;"
        f"names={names!r};"
        "print(json.dumps([name for name in names if importlib.util.find_spec(name) is None]))"
    )
    result = run_quiet([str(python), "-c", code], timeout=30)
    if result.returncode != 0:
        raise RuntimeError("H could not scan its Python dependencies:\n" + result.stdout[-1000:])
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("H dependency scan returned an unreadable result.") from exc
    return [str(name) for name in value]


def dependencies_ready(python: Path) -> bool:
    return dependency_marker_current() and not missing_imports(python)


def ensure_dependencies(python: Path) -> tuple[bool, list[str], bool]:
    marker_was_current = dependency_marker_current()
    missing_before = missing_imports(python)
    if marker_was_current and not missing_before:
        return False, missing_before, marker_was_current
    ensure_pip(python)
    print("H bootstrap: installing missing runtime dependencies...", flush=True)
    base_command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-q",
        "-r",
        str(REQUIREMENTS),
    ]
    result = run_quiet(base_command, timeout=600)
    if result.returncode != 0:
        result = run_quiet([*base_command, "--no-cache-dir"], timeout=600)
    if result.returncode != 0:
        raise RuntimeError("H dependency installation failed:\n" + result.stdout[-2000:])
    missing_after = missing_imports(python)
    if missing_after:
        raise RuntimeError("H dependency installation finished but imports are still missing: " + ", ".join(missing_after))
    DEPENDENCY_MARKER.write_text(RUNTIME_ID, encoding="ascii")
    return True, missing_before, marker_was_current


def bootstrap() -> BootstrapReport:
    packaged_core = packaged_core_path()
    if packaged_core:
        return BootstrapReport(
            python=str(packaged_core),
            environment_created=False,
            dependencies_installed=False,
            missing_before=[],
            marker_was_current=True,
            runtime_source="packaged-executable",
        )
    ensure_python_version()
    with BootstrapLock():
        python, environment_created = ensure_venv()
        dependencies_installed, missing_before, marker_was_current = ensure_dependencies(python)
    return BootstrapReport(
        python=str(python),
        environment_created=environment_created,
        dependencies_installed=dependencies_installed,
        missing_before=missing_before,
        marker_was_current=marker_was_current,
        runtime_source=os.environ.get("H_BOOTSTRAP_PYTHON_SOURCE", "direct-python"),
    )


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


def secret_present(value: str) -> bool:
    cleaned = value.strip().lstrip("\ufeff")
    return bool("".join(character for character in cleaned if character.isprintable() and not character.isspace()))


def key_file_present(path: Path) -> bool:
    try:
        return secret_present(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return False


def key_sources() -> list[str]:
    sources: list[str] = []
    if secret_present(os.environ.get("H_KIE_API_KEY", "")):
        sources.append("H_KIE_API_KEY")
    if secret_present(os.environ.get("KIE_API_KEY", "")):
        sources.append("KIE_API_KEY")
    if key_file_present(USER_KEY_FILE):
        sources.append("<home>/.codex/secrets/h_kie_api_key.txt")
    if key_file_present(LOCAL_KEY_FILE):
        sources.append("plugin-local .h_api_key")
    return sources


def plugin_version() -> str:
    manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        return "unknown"


def write_ready(report: BootstrapReport, checks: dict[str, object]) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    data = {
        "ready": True,
        "api_verified": True,
        "time": int(time.time()),
        "python": report.python,
        "plugin_root": str(PLUGIN_ROOT),
        "plugin_version": plugin_version(),
        "requirements_hash": RUNTIME_ID,
        "checks": checks,
    }
    READY_FILE.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def ready_cache_valid() -> bool:
    try:
        data = json.loads(READY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        data.get("ready")
        and data.get("api_verified")
        and data.get("requirements_hash") == RUNTIME_ID
        and data.get("plugin_version") == plugin_version()
    )


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


def local_checks(report: BootstrapReport, *, offline: bool, forwarded_args: list[str]) -> dict[str, object]:
    sources = key_sources()
    if "--api-key" in forwarded_args:
        sources = ["--api-key", *sources]
    packaged = report.runtime_source == "packaged-executable"
    runtime_path = Path(report.python)
    return {
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "python_supported": sys.version_info >= MIN_PYTHON,
        "requirements": REQUIREMENTS.exists(),
        "dependencies": runtime_path.is_file() if packaged else dependencies_ready(runtime_path),
        "main_script": runtime_path.is_file() if packaged else MAIN_SCRIPT.exists(),
        "desktop": str(desktop_dir()),
        "desktop_writable": desktop_writable(),
        "kie_key_sources": sources,
        "runtime": report.python if packaged else str(VENV_DIR),
        "portable": packaged,
        "offline": offline,
    }


def core_command(report: BootstrapReport, arguments: list[str]) -> list[str]:
    if report.runtime_source == "packaged-executable":
        return [report.python, *arguments]
    return [report.python, str(MAIN_SCRIPT), *arguments]


def run_api_doctor(report: BootstrapReport, forwarded_args: list[str]) -> tuple[int, dict[str, object], str]:
    result = run_quiet(
        core_command(report, ["doctor", *forwarded_args]),
        cwd=PLUGIN_ROOT,
        timeout=60,
    )
    return result.returncode, parse_last_json(result.stdout), result.stdout


def doctor(*, offline: bool = False, forwarded_args: list[str] | None = None) -> int:
    report = bootstrap()
    forwarded_args = forwarded_args or []
    checks = local_checks(report, offline=offline, forwarded_args=forwarded_args)
    sources = checks["kie_key_sources"]
    local_ready = all(
        bool(checks[name])
        for name in ("python_supported", "requirements", "dependencies", "main_script", "desktop_writable")
    ) and (bool(sources) or offline)
    api_ready = offline
    if local_ready and not offline:
        code, api_result, raw_output = run_api_doctor(report, forwarded_args)
        checks["kie_api"] = api_result or {"ready": False, "message": raw_output[-1000:]}
        api_ready = code == 0 and bool(api_result.get("ready"))
    ready = local_ready and api_ready
    if ready and not offline:
        write_ready(report, checks)
    print_json({"ready": ready, "bootstrap": asdict(report), "checks": checks})
    return 0 if ready else 1


def model_catalog(report: BootstrapReport) -> dict[str, Any]:
    result = run_quiet(core_command(report, ["catalog"]), cwd=PLUGIN_ROOT, timeout=60)
    catalog = parse_last_json(result.stdout)
    if result.returncode != 0 or not catalog:
        raise RuntimeError("H could not read its model catalog:\n" + result.stdout[-1000:])
    return catalog


def catalog_lines(items: list[dict[str, Any]], kind: str) -> str:
    lines: list[str] = []
    for item in items:
        choice = item.get("choice", "")
        name = item.get("name", item.get("model", ""))
        if kind == "image":
            limit = item.get("max_reference_images", 0)
            detail = f"0 张参考图=文生图，1-{limit} 张=多图参考"
        elif kind == "video":
            fixed = item.get("fixed_seconds")
            maximum = item.get("max_seconds")
            duration = f"固定约 {fixed} 秒" if fixed else f"最长 {maximum} 秒" if maximum else "时长按 Kie 当前支持"
            detail = f"{duration}；{item.get('input_rule', '')}"
        else:
            detail = ""
        suffix = f"（{detail}）" if detail else ""
        lines.append(f"{choice}. {name}{suffix}")
    return "\n".join(lines)


def protocol_display(state: str, catalog: dict[str, Any]) -> str:
    state = state.strip().lower().replace("_", "-")
    text_models = catalog_lines(list(catalog.get("text", [])), "text")
    image_models = catalog_lines(list(catalog.get("image", [])), "image")
    video_items = list(catalog.get("video", []))
    batch_video_items = [item for item in video_items if not str(item.get("input_rule", "")).startswith("已有Kie")]
    video_models = catalog_lines(video_items, "video")
    batch_video_models = catalog_lines(batch_video_items, "video")
    menus = {
        "mode": MODE_MENU,
        "batch-root": "请发送要批处理的根文件夹路径。H 会递归扫描整个根目录，并把全部合格图片放进同一个并发池。",
        "batch-image": (
            "请一次回复：图片模型编号 / 分辨率编号 / 比例编号 / 图片反推文本模型编号 / 图片反推元提示词。\n\n"
            f"图片模型：\n{image_models}\n\n"
            "分辨率：\n1. 1K\n2. 2K\n3. 4K\n\n"
            "比例：\n1. 9:16\n2. 16:9\n\n"
            f"图片反推文本模型：\n{text_models}\n\n"
            "图片反推元提示词直接回车使用中文默认值。"
        ),
        "batch-video": (
            "请一次回复：视频模型编号 / 时长秒数 / 分辨率 / 比例编号 / 视频反推文本模型编号 / 视频反推元提示词。\n\n"
            f"视频模型：\n{batch_video_models}\n\n"
            "分辨率：480p / 720p / 1080p（Veo 仅 720p/1080p；Gemini Omni 由模型决定）\n"
            "比例：1. 9:16  2. 16:9\n\n"
            f"视频反推文本模型：\n{text_models}\n\n"
            "视频反推元提示词直接回车使用中文默认值。"
        ),
        "single-kind": "请选择单处理类型，回复编号即可：\n1. 文本\n2. 图像\n3. 视频",
        "single-text": f"请选择文本模型并发送 prompt：\n{text_models}",
        "single-image": (
            "请一次发送：图片模型编号 / 分辨率编号 / 比例编号 / prompt / 参考图片。参考图片可不传，也可一次传多张。\n\n"
            f"图片模型：\n{image_models}\n\n"
            "分辨率：\n1. 1K\n2. 2K\n3. 4K\n\n"
            "比例：\n1. 9:16\n2. 16:9"
        ),
        "single-video": (
            "请一次发送：视频模型编号 / 时长秒数 / 分辨率 / 比例编号 / prompt / 所需图片、视频、音频或 Kie 任务 ID。\n\n"
            f"视频模型：\n{video_models}"
        ),
        "post-images": "请选择下一步：\n1. 继续生成视频\n2. 只重试失败项\n3. 处理新的文件夹\n4. 结束",
        "post-videos": "请选择下一步：\n1. 只重试失败项\n2. 处理新的文件夹\n3. 结束",
        "post-single": (
            "请选择下一步：\n"
            "1. 重试或继续当前任务（已提交任务只查询，不重复提交）\n"
            "2. 继续新的单处理\n3. 切换到批处理\n4. 结束"
        ),
    }
    if state not in menus:
        raise ValueError(f"Unknown H protocol state: {state}")
    return menus[state]


def protocol(state: str) -> int:
    report = bootstrap()
    catalog: dict[str, Any] = {}
    normalized = state.strip().lower().replace("_", "-")
    if normalized not in {"mode", "batch-root", "single-kind", "post-images", "post-videos", "post-single"}:
        catalog = model_catalog(report)
    print_json(
        {
            "ready": True,
            "protocol_version": PROTOCOL_VERSION,
            "state": normalized,
            "bootstrap": asdict(report),
            "display_text": protocol_display(normalized, catalog),
        }
    )
    return 0


def setup_status(report: BootstrapReport) -> str:
    if report.runtime_source == "packaged-executable":
        return "内置运行环境已就绪，无需安装 Python。"
    if report.environment_created or report.dependencies_installed:
        return "首次环境准备完成，缺失依赖已自动安装。"
    return "环境检查通过，H 已准备好。"


def category_label(category: str) -> str:
    labels = {
        "authentication": "Kie 密钥无效或已失效",
        "quota": "Kie 额度不足",
        "validation": "请求参数不符合模型要求",
        "rate_limit": "Kie 接口限流",
        "maintenance": "Kie 服务维护中",
        "provider": "上游模型服务异常",
        "network": "网络、代理或 TLS 连接异常",
        "runtime": "本地运行环境异常",
    }
    return labels.get(category, "未分类错误")


def safe_reason(value: object) -> str:
    text = " ".join(str(value or "未知原因").split())
    return text[:500]


def start(*, offline: bool = False, force_check: bool = False, forwarded_args: list[str] | None = None) -> int:
    report = bootstrap()
    forwarded_args = forwarded_args or []
    checks = local_checks(report, offline=offline, forwarded_args=forwarded_args)
    status = setup_status(report)
    if not checks["desktop_writable"]:
        display = f"{GREETING}\n\nH 自动环境准备失败。\n归因：桌面目录不可写。\n请修复桌面目录权限后重新调用 H。"
        print_json({"ready": False, "state": "setup-error", "bootstrap": asdict(report), "checks": checks, "display_text": display})
        return 0
    if offline:
        print_json(
            {
                "ready": True,
                "state": "mode",
                "protocol_version": PROTOCOL_VERSION,
                "bootstrap": asdict(report),
                "checks": checks,
                "display_text": f"{GREETING}\n\n{status}\n\n{MODE_MENU}",
            }
        )
        return 0
    if not checks["kie_key_sources"]:
        display = (
            f"{GREETING}\n\n{status}\n\n"
            "尚未检测到 Kie API Key。请先设置一次密钥；H 不会把密钥写入仓库或输出日志。"
        )
        print_json({"ready": False, "state": "key-required", "bootstrap": asdict(report), "checks": checks, "display_text": display})
        return 0
    if ready_cache_valid() and not force_check:
        print_json(
            {
                "ready": True,
                "state": "mode",
                "protocol_version": PROTOCOL_VERSION,
                "bootstrap": asdict(report),
                "checks": checks,
                "display_text": f"{GREETING}\n\n{status}\n\n{MODE_MENU}",
            }
        )
        return 0
    code, api_result, raw_output = run_api_doctor(report, forwarded_args)
    checks["kie_api"] = api_result or {"ready": False, "message": raw_output[-1000:]}
    if code == 0 and api_result.get("ready"):
        write_ready(report, checks)
        print_json(
            {
                "ready": True,
                "state": "mode",
                "protocol_version": PROTOCOL_VERSION,
                "bootstrap": asdict(report),
                "checks": checks,
                "display_text": f"{GREETING}\n\n{status}\n\n{MODE_MENU}",
            }
        )
        return 0
    category = str(api_result.get("error_category") or api_result.get("category") or "runtime")
    reason = safe_reason(api_result.get("error") or api_result.get("message") or raw_output[-500:])
    display = (
        f"{GREETING}\n\n本地环境已经准备完成，但 Kie 验证失败。\n"
        f"归因：{category_label(category)}。\n原因：{reason}\n"
        "请修正后重新调用 H；验证失败时不会提交任何生成任务。"
    )
    print_json(
        {
            "ready": False,
            "state": "setup-error",
            "error_category": category,
            "bootstrap": asdict(report),
            "checks": checks,
            "display_text": display,
        }
    )
    return 0


def install_home() -> Path:
    override = os.environ.get("H_INSTALL_HOME", "").strip()
    return Path(override).expanduser().resolve() if override else Path.home().resolve()


def merge_personal_marketplace(path: Path) -> None:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Personal marketplace JSON is invalid: {path}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Personal marketplace must contain a JSON object: {path}")
    else:
        data = {}
    data.setdefault("name", "personal")
    interface = data.setdefault("interface", {})
    if not isinstance(interface, dict):
        interface = {}
        data["interface"] = interface
    interface.setdefault("displayName", "Personal")
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        raise RuntimeError(f"Personal marketplace plugins must be a list: {path}")
    entry = {
        "name": "h",
        "source": {"source": "local", "path": "./plugins/h"},
        "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_USE"},
        "category": "Productivity",
    }
    merged: list[object] = []
    replaced = False
    for plugin in plugins:
        if isinstance(plugin, dict) and plugin.get("name") == "h":
            if not replaced:
                merged.append(entry)
                replaced = True
            continue
        merged.append(plugin)
    if not replaced:
        merged.append(entry)
    data["plugins"] = merged
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"marketplace.backup-{int(time.time())}.json")
        shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def install_local() -> int:
    packaged_core = packaged_core_path()
    if not packaged_core:
        raise RuntimeError("This package does not contain the portable H runtime.")
    source = PLUGIN_ROOT.resolve()
    home = install_home()
    marketplace_root = home / ".agents" / "plugins"
    target = marketplace_root / "plugins" / "h"
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if source != target.resolve():
        staging = target.parent / f".h.installing-{os.getpid()}-{int(time.time())}"
        ignore = shutil.ignore_patterns(
            ".git",
            ".github",
            ".agents",
            ".h_api_key",
            ".h_ready.json",
            ".h_venv",
            ".ruff_cache",
            "__pycache__",
            "*.pyc",
            "build",
            "dist",
            "portable-dist",
        )
        preserved_key = (target / ".h_api_key").read_bytes() if (target / ".h_api_key").is_file() else None
        shutil.copytree(source, staging, ignore=ignore)
        if preserved_key:
            (staging / ".h_api_key").write_bytes(preserved_key)
        if target.exists():
            backup = target.parent / f"h.backup-{int(time.time())}-{os.getpid()}"
            target.rename(backup)
        staging.rename(target)
    runtime_dir = target / "runtime"
    launcher_name = "h_launcher.exe" if os.name == "nt" else "h_launcher"
    core_name = "h_core.exe" if os.name == "nt" else "h_core"
    installed_launcher = runtime_dir / launcher_name
    installed_core = runtime_dir / core_name
    if not installed_launcher.is_file() or not installed_core.is_file():
        raise RuntimeError("The copied H package is missing its portable runtime files.")
    if os.name != "nt":
        installed_launcher.chmod(installed_launcher.stat().st_mode | 0o111)
        installed_core.chmod(installed_core.stat().st_mode | 0o111)
        if sys.platform == "darwin":
            run_quiet(["xattr", "-dr", "com.apple.quarantine", str(target)], timeout=30)
    environment = {"CODEX_HOME": str(home / ".codex")} if os.environ.get("H_INSTALL_HOME") else None
    smoke = run_quiet(
        [str(installed_launcher), "start", "--offline"],
        cwd=target,
        timeout=300,
        env_overrides=environment,
    )
    smoke_payload = parse_last_json(smoke.stdout)
    if smoke.returncode != 0 or not smoke_payload.get("ready"):
        if backup and target.exists():
            failed = target.parent / f"h.failed-{int(time.time())}-{os.getpid()}"
            target.rename(failed)
            backup.rename(target)
        raise RuntimeError("The installed H portable runtime did not pass its offline startup check.")
    marketplace_path = marketplace_root / "marketplace.json"
    merge_personal_marketplace(marketplace_path)
    print_json(
        {
            "ready": True,
            "state": "installed",
            "plugin_path": str(target),
            "marketplace_path": str(marketplace_path),
            "backup_path": str(backup) if backup else "",
            "portable_runtime": True,
            "display_text": (
                "H 安装完成，内置运行环境已通过检查，不需要安装 Python。\n"
                "请完全退出并重新打开 Codex，然后新建任务调用 H。"
            ),
        }
    )
    return 0


def set_key() -> int:
    value = getpass.getpass("Kie API key: ").strip().lstrip("\ufeff")
    value = "".join(ch for ch in value if ch.isprintable() and not ch.isspace())
    if not value:
        raise RuntimeError("No Kie API key was entered.")
    USER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_KEY_FILE.write_text(value, encoding="utf-8")
    print(f"Kie API key saved to {USER_KEY_FILE}", flush=True)
    return 0


def startup_failure(exc: Exception) -> dict[str, Any]:
    reason = safe_reason(exc)
    return {
        "ready": False,
        "state": "setup-error",
        "error_category": "runtime",
        "protocol_version": PROTOCOL_VERSION,
        "display_text": (
            f"{GREETING}\n\nH 自动环境准备失败。\n归因：本地运行环境异常。\n"
            f"原因：{reason}\nH 尚未提交任何生成任务。"
        ),
    }


def main(argv: list[str]) -> int:
    configure_utf8_output()
    command = argv[0] if argv else "start"
    try:
        if command == "install-local":
            return install_local()
        if command == "set-key":
            return set_key()
        if command in {"bootstrap", "--bootstrap"}:
            return doctor(offline=True)
        if command in {"--doctor", "doctor"}:
            extra = [value for value in argv[1:] if value != "--offline"]
            return doctor(offline="--offline" in argv[1:], forwarded_args=extra)
        if command == "start":
            extra = [value for value in argv[1:] if value not in {"--offline", "--force-check"}]
            return start(
                offline="--offline" in argv[1:],
                force_check="--force-check" in argv[1:],
                forwarded_args=extra,
            )
        if command == "protocol":
            if len(argv) != 2:
                raise ValueError("Usage: h_run protocol <state>")
            return protocol(argv[1])
        report = bootstrap()
        return subprocess.call(core_command(report, argv), cwd=str(PLUGIN_ROOT))
    except Exception as exc:
        if command in {"start", "protocol"}:
            print_json(startup_failure(exc))
            return 0
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print_json({"ready": False, "error_category": "runtime", "error": safe_reason(exc)})
        raise SystemExit(1)
