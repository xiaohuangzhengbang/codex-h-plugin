import importlib.util
import io
import sys
from pathlib import Path
from contextlib import redirect_stdout


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
    assert launcher.protocol_display("mode", {}) == "请选择处理模式，回复编号即可：\n1. 批处理\n2. 单处理"
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
    }
    launcher.bootstrap = lambda: report
    launcher.local_checks = lambda *_args, **_kwargs: {
        "desktop_writable": True,
        "kie_key_sources": ["test-key-source"],
    }
    launcher.ready_cache_valid = lambda: False
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
    assert "Python.Python.3.12" in windows
    assert "winget.exe" in windows
    assert "powershell.exe" in command

    assert "codex-runtimes" in shell
    assert "/opt/homebrew/bin/brew" in shell
    assert "/usr/local/bin/brew" in shell
    assert "python@3.12" in shell


def test_user_facing_files_are_valid_utf8_chinese():
    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "skills" / "h" / "SKILL.md").read_text(encoding="utf-8")
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")

    assert "哈喽小杨，你又开始工作啦，想不想小黄啊？" in launcher_source
    assert "H 固定控制器" in skill
    assert "首次自动准备" in readme
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
