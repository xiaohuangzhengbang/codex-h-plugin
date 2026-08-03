import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
LAUNCHER = SCRIPT_DIR / "h_run.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("h_run_under_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_catalog():
    return {
        "text": [
            {"choice": "1", "name": "GPT 5.5 Response", "model": "gpt-5-5"},
            {"choice": "2", "name": "GPT 5.4 Response", "model": "gpt-5-4"},
        ],
        "image": [
            {
                "choice": "1",
                "name": "GPT Image-2",
                "model": "gpt-image-2",
                "max_reference_images": 16,
            }
        ],
        "video": [
            {
                "choice": "1",
                "name": "Grok Imagine",
                "model": "grok-imagine",
                "max_seconds": 30,
                "fixed_seconds": None,
                "input_rule": "Grok: 0图文生，1图图生",
            },
            {
                "choice": "3",
                "name": "Veo3.1 Lite",
                "model": "veo3.1-lite",
                "max_seconds": 8,
                "fixed_seconds": 8,
                "input_rule": "Veo: 0图文生，1-2图首尾帧，3图仅Lite/Fast参考图",
            },
            {
                "choice": "10",
                "name": "Grok Upscale",
                "model": "grok-upscale",
                "max_seconds": None,
                "fixed_seconds": None,
                "input_rule": "已有Kie Grok视频task_id",
            },
        ],
    }


def test_fixed_protocol_menus():
    launcher = load_launcher()
    assert launcher.protocol_display("mode", {}) == "请选择处理模式，回复编号即可：\n1. 批处理\n2. 单处理\n3. 发布"
    assert launcher.protocol_display("single-kind", {}) == "请选择单处理类型，回复编号即可：\n1. 文本\n2. 图像\n3. 视频"

    image_menu = launcher.protocol_display("batch-image", sample_catalog())
    assert "GPT Image-2（0 张参考图=文生图，1-16 张=多图参考）" in image_menu
    assert "1. 1K" in image_menu
    assert "2. 2K" in image_menu
    assert "3. 4K" in image_menu
    assert "图片反推文本模型" in image_menu
    assert "GPT 5.5 Response" in image_menu

    video_menu = launcher.protocol_display("single-video", sample_catalog())
    assert "Grok Imagine（最长 30 秒" in video_menu
    assert "Veo3.1 Lite（固定约 8 秒" in video_menu
    assert "Grok Upscale" in video_menu

    batch_video_menu = launcher.protocol_display("batch-video", sample_catalog())
    assert "Grok Upscale" not in batch_video_menu
    assert "发布本次生成的视频" in launcher.protocol_display("post-videos", {})
    assert "发布本次生成的视频" in launcher.protocol_display("post-single-video", {})
    assert "H 已生成的视频结果" in launcher.protocol_display("publish-source", {})
    assert "输入 FABU 正式发布" in launcher.protocol_display("publish-confirm", {})


def test_no_arguments_defaults_to_start():
    launcher = load_launcher()
    calls = []
    original = launcher.start
    launcher.start = lambda **kwargs: calls.append(kwargs) or 17
    try:
        assert launcher.main([]) == 17
    finally:
        launcher.start = original
    assert calls == [{"offline": False, "force_check": False, "forwarded_args": []}]


def test_adspower_command_reexecs_inside_the_prepared_private_python():
    launcher = load_launcher()
    report = launcher.BootstrapReport(
        python=str(Path(sys.executable).with_name("h-private-python")),
        environment_created=False,
        dependencies_installed=False,
        missing_before=[],
        marker_was_current=True,
        runtime_source="test-python",
    )
    calls = []
    originals = {"bootstrap": launcher.bootstrap, "subprocess_call": launcher.subprocess.call}
    launcher.bootstrap = lambda: report
    launcher.subprocess.call = lambda command, **kwargs: calls.append((command, kwargs)) or 23
    try:
        assert launcher.main(["adspower", "runtime"]) == 23
    finally:
        launcher.bootstrap = originals["bootstrap"]
        launcher.subprocess.call = originals["subprocess_call"]
    assert calls[0][0][0] == report.python
    assert calls[0][0][-2:] == ["adspower", "runtime"]


def test_dependency_scanner_detects_missing_imports():
    launcher = load_launcher()
    missing = launcher.missing_imports(
        Path(sys.executable),
        ["json", "h_dependency_that_must_not_exist_7f643b"],
    )
    assert missing == ["h_dependency_that_must_not_exist_7f643b"]


def test_empty_or_bom_only_keys_are_not_detected():
    launcher = load_launcher()
    assert not launcher.secret_present("")
    assert not launcher.secret_present("\ufeff \n\t")
    assert launcher.secret_present("valid-key-value")


def test_packaged_runtime_skips_python_command_shape():
    launcher = load_launcher()
    report = launcher.BootstrapReport(
        python="/package/runtime/h_core",
        environment_created=False,
        dependencies_installed=False,
        missing_before=[],
        marker_was_current=True,
        runtime_source="packaged-executable",
    )
    assert launcher.core_command(report, ["catalog"]) == ["/package/runtime/h_core", "catalog"]
    assert launcher.setup_status(report) == "内置运行环境已就绪，无需安装 Python。"


def test_local_installer_merges_marketplace_and_preserves_other_plugins():
    launcher = load_launcher()
    launcher_name = "h_launcher.exe" if os.name == "nt" else "h_launcher"
    core_name = "h_core.exe" if os.name == "nt" else "h_core"
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source"
        home = root / "home"
        (source / ".codex-plugin").mkdir(parents=True)
        (source / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "h", "version": "0.2.0+codex.test"}),
            encoding="utf-8",
        )
        (source / "runtime").mkdir()
        (source / "runtime" / launcher_name).write_bytes(b"launcher")
        (source / "runtime" / core_name).write_bytes(b"core")
        (source / "requirements.txt").write_text("requests\n", encoding="utf-8")
        marketplace = home / ".agents" / "plugins" / "marketplace.json"
        marketplace.parent.mkdir(parents=True)
        marketplace.write_text(
            json.dumps(
                {
                    "name": "personal",
                    "interface": {"displayName": "Personal"},
                    "plugins": [
                        {"name": "kie", "source": {"source": "local", "path": "./plugins/kie"}},
                        {"name": "h", "source": {"source": "local", "path": "old"}},
                    ],
                }
            ),
            encoding="utf-8",
        )
        originals = {
            "PLUGIN_ROOT": launcher.PLUGIN_ROOT,
            "packaged_core_path": launcher.packaged_core_path,
            "run_quiet": launcher.run_quiet,
        }
        old_home = os.environ.get("H_INSTALL_HOME")
        launcher.PLUGIN_ROOT = source
        launcher.packaged_core_path = lambda: source / "runtime" / core_name
        launcher.run_quiet = lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ready": True}),
        )
        os.environ["H_INSTALL_HOME"] = str(home)
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                assert launcher.install_local() == 0
        finally:
            launcher.PLUGIN_ROOT = originals["PLUGIN_ROOT"]
            launcher.packaged_core_path = originals["packaged_core_path"]
            launcher.run_quiet = originals["run_quiet"]
            if old_home is None:
                os.environ.pop("H_INSTALL_HOME", None)
            else:
                os.environ["H_INSTALL_HOME"] = old_home
        payload = launcher.parse_last_json(output.getvalue())
        assert payload["ready"] is True
        assert payload["portable_runtime"] is True
        target = home / ".agents" / "plugins" / "plugins" / "h"
        assert (target / "runtime" / launcher_name).is_file()
        installed_marketplace = json.loads(marketplace.read_text(encoding="utf-8"))
        assert [plugin["name"] for plugin in installed_marketplace["plugins"]] == ["kie", "h"]
        h_entry = installed_marketplace["plugins"][1]
        assert h_entry["source"]["path"] == "./plugins/h"
        assert h_entry["policy"]["installation"] == "INSTALLED_BY_DEFAULT"


def test_start_attributes_api_failure_without_submitting_work():
    launcher = load_launcher()
    report = launcher.BootstrapReport(
        python=sys.executable,
        environment_created=False,
        dependencies_installed=False,
        missing_before=[],
        marker_was_current=True,
        runtime_source="test",
    )
    originals = {
        "bootstrap": launcher.bootstrap,
        "local_checks": launcher.local_checks,
        "ready_cache_valid": launcher.ready_cache_valid,
        "run_api_doctor": launcher.run_api_doctor,
        "ensure_adspower_runtime": launcher.ensure_adspower_runtime,
    }
    launcher.bootstrap = lambda: report
    launcher.local_checks = lambda *_args, **_kwargs: {
        "desktop_writable": True,
        "kie_key_sources": ["test-key-source"],
    }
    launcher.ready_cache_valid = lambda: False
    launcher.ensure_adspower_runtime = lambda **_kwargs: {"ready": True, "source": "test"}
    launcher.run_api_doctor = lambda *_args, **_kwargs: (
        1,
        {"ready": False, "error_category": "authentication", "error": "invalid key"},
        "",
    )
    try:
        output = io.StringIO()
        with redirect_stdout(output):
            assert launcher.start(force_check=True) == 0
    finally:
        for name, value in originals.items():
            setattr(launcher, name, value)
    payload = launcher.parse_last_json(output.getvalue())
    assert payload["state"] == "setup-error"
    assert payload["error_category"] == "authentication"
    assert "Kie 密钥无效或已失效" in payload["display_text"]
    assert "不会提交任何生成任务" in payload["display_text"]


def test_cross_platform_bootstrap_sources_are_present():
    windows = (SCRIPT_DIR / "h_bootstrap.ps1").read_text(encoding="utf-8")
    shell = (SCRIPT_DIR / "h_run.sh").read_text(encoding="utf-8")
    command = (SCRIPT_DIR / "h_run.cmd").read_text(encoding="utf-8")

    assert all(ord(character) < 128 for character in windows)
    assert "codex-runtimes" in windows
    assert "github-runtime" in windows
    assert "Invoke-WebRequest" in windows
    assert "System.Security.Cryptography.SHA256" in windows
    assert "Get-FileHash" not in windows
    assert "H_FORCE_GITHUB_RUNTIME" in windows
    assert "H-Codex-Plugin-Windows-x64.zip" in windows
    assert "82a09fce5278714f8e968b2c92a907d00d0600d8235cb5f45444862f6b12c10e" in windows
    assert "Python.Python.3.12" in windows
    assert "winget.exe" in windows
    assert "powershell.exe" in command

    assert "codex-runtimes" in shell
    assert "github-runtime" in shell
    assert "H_FORCE_GITHUB_RUNTIME" in shell
    assert "H-Codex-Plugin-macOS-Apple-Silicon.zip" in shell
    assert "H-Codex-Plugin-macOS-Intel.zip" in shell
    assert "1681496aca685912a8728284f956bdd292121cce77e00302b92dbe8981c489ea" in shell
    assert "ce4e0fb9e5da5964946b3a8d3d5c95797c19d62819fa4fa669c75dfb1efd74e1" in shell
    assert "curl -fL --retry 3" in shell
    assert "shasum -a 256" in shell
    assert "/opt/homebrew/bin/brew" in shell
    assert "/usr/local/bin/brew" in shell
    assert "python@3.12" in shell


def test_adspower_runtime_is_bundled_and_node_downloads_are_pinned():
    launcher = load_launcher()
    assert launcher.adspower_dependencies_ready()
    assert launcher.NODE_VERSION.startswith("v24.")
    assert set(launcher.NODE_ASSETS) == {"windows-x64", "macos-intel", "macos-apple-silicon"}
    assert all(len(item["sha256"]) == 64 for item in launcher.NODE_ASSETS.values())
    assert (PLUGIN_ROOT / "scripts" / "adspower_runtime" / "node_modules" / "playwright" / "package.json").is_file()
    assert "openpyxl" in launcher.REQUIRED_IMPORTS
    assert not (PLUGIN_ROOT / "scripts" / "adspower_runtime" / "node_modules" / "xlsx").exists()
    build_source = (SCRIPT_DIR / "build_portable.py").read_text(encoding="utf-8")
    assert 'PAYLOAD_SCRIPT_DIRECTORIES = ["adspower_runtime"]' in build_source
    assert 'collect_packages=("openpyxl",)' in build_source


def test_missing_node_is_automatically_downloaded_once():
    launcher = load_launcher()
    calls = []

    class FakeLock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    originals = {
        "adspower_dependencies_ready": launcher.adspower_dependencies_ready,
        "node_platform_id": launcher.node_platform_id,
        "node_works": launcher.node_works,
        "which": launcher.shutil.which,
        "download_node_runtime": launcher.download_node_runtime,
        "run_quiet": launcher.run_quiet,
        "BootstrapLock": launcher.BootstrapLock,
    }
    launcher.adspower_dependencies_ready = lambda: True
    launcher.node_platform_id = lambda: "macos-apple-silicon"
    launcher.node_works = lambda _path: False
    launcher.shutil.which = lambda _name: None
    launcher.download_node_runtime = lambda platform_id: calls.append(platform_id) or Path("/cache/node")
    launcher.run_quiet = lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="v24.18.1\n")
    launcher.BootstrapLock = FakeLock
    try:
        result = launcher.ensure_adspower_runtime(install=True)
    finally:
        for name, value in originals.items():
            if name == "which":
                launcher.shutil.which = value
            else:
                setattr(launcher, name, value)
    assert calls == ["macos-apple-silicon"]
    assert result["ready"] is True
    assert result["source"] == "downloaded-verified"


def test_github_marketplace_install_contract():
    marketplace = json.loads(
        (PLUGIN_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in marketplace["plugins"] if item["name"] == "h")
    assert marketplace["name"] == "codex-h-plugin"
    assert entry["source"] == {
        "source": "url",
        "url": "https://github.com/xiaohuangzhengbang/codex-h-plugin.git",
        "ref": "main",
    }
    assert entry["policy"]["installation"] == "INSTALLED_BY_DEFAULT"
    assert entry["policy"]["authentication"] == "ON_USE"

    agents = (PLUGIN_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    install = (PLUGIN_ROOT / "INSTALL.md").read_text(encoding="utf-8")
    for document in (agents, install):
        assert (
            "plugin marketplace add https://github.com/xiaohuangzhengbang/codex-h-plugin.git --ref main"
            in document
        )
        assert "plugin add h@codex-h-plugin" in document
    assert "Do not redirect the user to a ZIP package" in agents
    assert "WindowsApps" in agents


def test_user_facing_files_are_valid_utf8_chinese():
    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "skills" / "h" / "SKILL.md").read_text(encoding="utf-8")
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")

    assert "哈喽小杨，你又开始工作啦，想不想小黄啊？" in launcher_source
    assert "H 固定控制器" in skill
    assert "从 GitHub 安装" in readme
    assert "�" not in launcher_source + skill + readme


def test_startup_failure_is_non_generating_and_actionable():
    launcher = load_launcher()
    payload = launcher.startup_failure(RuntimeError("dependency install failed"))
    assert payload["state"] == "setup-error"
    assert payload["error_category"] == "runtime"
    assert "尚未提交任何生成任务" in payload["display_text"]


def run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} H launcher tests")


if __name__ == "__main__":
    run_all()
