import importlib.util
import io
import json
import os
import sys
import tempfile
import zipfile
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
    assert launcher.protocol_display("mode", {}) == "请选择功能，回复编号即可：\n1. PID\n2. 生成\n3. 发布"
    assert launcher.protocol_display("generate-mode", {}) == "请选择生成方式，回复编号即可：\n1. 批处理\n2. 单处理"
    assert "FastMoss" in launcher.protocol_display("pid", {})
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
    assert "AI 分析文本模型" in launcher.protocol_display("pid-video", sample_catalog())
    publish_plan = launcher.protocol_display("publish-plan", {})
    assert "30 分钟" in publish_plan
    assert "PID 视频必须挂同一个完整数字 PID" in publish_plan


def test_no_arguments_defaults_to_start():
    launcher = load_launcher()
    calls = []
    original = launcher.start
    launcher.start = lambda **kwargs: calls.append(kwargs) or 17
    try:
        assert launcher.main([]) == 17
    finally:
        launcher.start = original
    assert calls == [
        {
            "offline": False,
            "force_check": False,
            "capability": "menu",
            "forwarded_args": [],
        }
    ]


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


def test_fastmoss_command_reexecs_inside_the_prepared_private_python():
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
    launcher.subprocess.call = lambda command, **kwargs: calls.append((command, kwargs)) or 29
    try:
        assert launcher.main(["fastmoss", "status"]) == 29
    finally:
        launcher.bootstrap = originals["bootstrap"]
        launcher.subprocess.call = originals["subprocess_call"]
    assert calls[0][0][0] == report.python
    assert calls[0][0][-2:] == ["fastmoss", "status"]


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
        "fastmoss_key_sources": [],
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
            assert launcher.start(force_check=True, capability="generate") == 0
    finally:
        for name, value in originals.items():
            setattr(launcher, name, value)
    payload = launcher.parse_last_json(output.getvalue())
    assert payload["state"] == "setup-error"
    assert payload["error_category"] == "authentication"
    assert "Kie 密钥无效或已失效" in payload["display_text"]
    assert "不会提交任何生成任务" in payload["display_text"]


def test_start_menu_does_not_require_kie_or_fastmoss_keys():
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
        "ensure_adspower_runtime": launcher.ensure_adspower_runtime,
    }
    launcher.bootstrap = lambda: report
    launcher.local_checks = lambda *_args, **_kwargs: {
        "desktop_writable": True,
        "kie_key_sources": [],
        "fastmoss_key_sources": [],
    }
    adspower_calls = []
    launcher.ensure_adspower_runtime = lambda **_kwargs: adspower_calls.append(True) or {
        "ready": True,
        "source": "test",
    }
    try:
        output = io.StringIO()
        with redirect_stdout(output):
            assert launcher.start(capability="menu") == 0
    finally:
        for name, value in originals.items():
            setattr(launcher, name, value)
    payload = launcher.parse_last_json(output.getvalue())
    assert payload["ready"] is True
    assert payload["state"] == "mode"
    assert "1. PID" in payload["display_text"]
    assert payload["checks"]["adspower_runtime"]["skipped"] is True
    assert adspower_calls == []


def test_pid_uploaded_images_require_exact_one_to_one_mapping():
    launcher = load_launcher()
    pids = ["10000000001", "10000000002"]
    with tempfile.TemporaryDirectory() as temp_dir:
        first = Path(temp_dir) / "first.png"
        second = Path(temp_dir) / "second.jpg"
        first.write_bytes(b"\x89PNG\r\n\x1a\nimage")
        second.write_bytes(b"\xff\xd8\xffimage")
        mapping = launcher.map_pid_reference_images(pids, [str(first), str(second)])
        assert mapping == {pids[0]: first.resolve(), pids[1]: second.resolve()}
        try:
            launcher.map_pid_reference_images(pids, [str(first)])
            raise AssertionError("mismatched PID and image counts were accepted")
        except launcher.FastMossError as exc:
            assert exc.category == "validation"


def test_pid_capability_requires_only_fastmoss_key():
    launcher = load_launcher()
    report = launcher.BootstrapReport(
        python=sys.executable,
        environment_created=False,
        dependencies_installed=False,
        missing_before=[],
        marker_was_current=True,
        runtime_source="test",
    )
    originals = {"bootstrap": launcher.bootstrap, "local_checks": launcher.local_checks}
    launcher.bootstrap = lambda: report
    launcher.local_checks = lambda *_args, **_kwargs: {
        "desktop_writable": True,
        "kie_key_sources": [],
        "fastmoss_key_sources": ["test-fastmoss-key"],
    }
    try:
        output = io.StringIO()
        with redirect_stdout(output):
            assert launcher.start(capability="pid") == 0
    finally:
        for name, value in originals.items():
            setattr(launcher, name, value)
    payload = launcher.parse_last_json(output.getvalue())
    assert payload["ready"] is True
    assert payload["state"] == "pid"
    assert "FastMoss" in payload["display_text"]


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
    assert "portable-20260804031849" in windows
    assert "v0.4.0-portable.20260804031849" in windows
    assert "H-Codex-Plugin-Windows-x64.zip" in windows
    assert "8a8d07118a1b8e1859bd605973a77aededa7cb03af83fb5e967e07eafbd7bdf4" in windows
    assert "Python.Python.3.12" in windows
    assert "winget.exe" in windows
    assert "powershell.exe" in command

    assert "codex-runtimes" in shell
    assert "github-runtime" in shell
    assert "H_FORCE_GITHUB_RUNTIME" in shell
    assert "portable-20260804031849" in shell
    assert "v0.4.0-portable.20260804031849" in shell
    assert "H-Codex-Plugin-macOS-Apple-Silicon.zip" in shell
    assert "H-Codex-Plugin-macOS-Intel.zip" in shell
    assert "2fa491274d7f340157582936e2de08661b923abb9deea417bcda516e1a707ec3" in shell
    assert "e9492a49991b1d1f499634dc60f7e041176fb31e2dd61e5807e9694cb5220604" in shell
    assert "curl -fL --retry 3" in shell
    assert "shasum -a 256" in shell
    assert "/opt/homebrew/bin/brew" in shell
    assert "/usr/local/bin/brew" in shell
    assert "python@3.12" in shell


def test_adspower_runtime_is_bundled_and_node_downloads_are_pinned():
    launcher = load_launcher()
    assert launcher.ADSPOWER_RUNTIME_ARCHIVE.is_file()
    assert launcher.sha256_file(launcher.ADSPOWER_RUNTIME_ARCHIVE) == launcher.ADSPOWER_RUNTIME_SHA256
    with zipfile.ZipFile(launcher.ADSPOWER_RUNTIME_ARCHIVE) as archive:
        assert archive.namelist()
        assert all("\\" not in name and not name.startswith("/") for name in archive.namelist())
    prepared = launcher.ensure_adspower_payload()
    assert prepared == launcher.ADSPOWER_RUNTIME_DIR
    assert launcher.adspower_dependencies_ready()
    source_runtime = PLUGIN_ROOT / "scripts" / "adspower_runtime"
    for source in source_runtime.rglob("*"):
        if not source.is_file() or "node_modules" in source.parts:
            continue
        extracted = prepared / source.relative_to(source_runtime)
        assert extracted.is_file(), f"Bundled AdsPower runtime is missing {source.relative_to(source_runtime)}"
        assert extracted.read_bytes() == source.read_bytes(), f"Bundled AdsPower runtime is stale: {source}"
    assert launcher.NODE_VERSION.startswith("v24.")
    assert set(launcher.NODE_ASSETS) == {"windows-x64", "macos-intel", "macos-apple-silicon"}
    assert all(len(item["sha256"]) == 64 for item in launcher.NODE_ASSETS.values())
    assert "openpyxl" in launcher.REQUIRED_IMPORTS
    assert not (prepared / "node_modules" / "xlsx").exists()
    build_source = (SCRIPT_DIR / "build_portable.py").read_text(encoding="utf-8")
    assert 'PAYLOAD_SCRIPT_DIRECTORIES = ["adspower_runtime"]' in build_source
    assert 'ignore=shutil.ignore_patterns("node_modules")' in build_source
    assert '"fastmoss_client.py"' in build_source
    assert 'collect_packages=("openpyxl",)' in build_source
    assert (SCRIPT_DIR / "build_adspower_bundle.py").is_file()


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


def test_plugin_ui_has_exactly_pid_generation_and_publish_entries():
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    prompts = manifest["interface"]["defaultPrompt"]
    assert len(prompts) == 3
    assert "PID" in prompts[0] and "FastMoss" in prompts[0]
    assert "批处理或单处理" in prompts[1]
    assert "30 分钟" in prompts[2] and "原 PID" in prompts[2]
    assert manifest["interface"]["displayName"] == "H · PID / 生成 / 发布"

    skill_names = {
        path.parent.name
        for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")
    }
    assert {"h", "fastmoss-pid", "kie-generate", "adspower-publish"} <= skill_names
    fastmoss_ui = (PLUGIN_ROOT / "skills" / "fastmoss-pid" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
    generate_ui = (PLUGIN_ROOT / "skills" / "kie-generate" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
    publish_ui = (PLUGIN_ROOT / "skills" / "adspower-publish" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
    assert 'display_name: "H PID"' in fastmoss_ui
    assert 'display_name: "H 生成"' in generate_ui
    assert 'display_name: "H 发布"' in publish_ui


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
