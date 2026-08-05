import csv
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
LAUNCHER = SCRIPT_DIR / "h_run.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("h_run_adspower_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_mp4(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41")


def plan_args(video_root: Path, **overrides):
    values = {
        "video_root": str(video_root),
        "profile_no": ["27", "28"],
        "start_at": "2026-08-04 10:30",
        "interval_minutes": 30,
        "caption_template": "商品 {pid} 第 {index} 条 {filename}",
        "hashtags": "#TikTokShop #Menswear",
        "timezone": "Asia/Shanghai",
        "attach_pid": True,
        "publish_mode": "schedule",
        "plan_name": "schedule.generated.csv",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_generated_results_become_a_valid_round_robin_publish_plan():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "H返回结果_产品"
        text_dir = root / "文本"
        video_dir = root / "视频"
        text_dir.mkdir(parents=True)
        write_mp4(video_dir / "123456.mp4")
        write_mp4(video_dir / "789012.mp4")
        (video_dir / "bad.mp4").write_bytes(b"\x89PNG\r\n\x1a\nnot-a-video")
        (text_dir / "123456.video.json").write_text(
            json.dumps({"state": "success", "pid": "123456", "video_path": str(video_dir / "123456.mp4")}),
            encoding="utf-8",
        )
        (text_dir / "789012.video.json").write_text(
            json.dumps({"state": "success", "pid": "789012", "video_path": str(video_dir / "789012.mp4")}),
            encoding="utf-8",
        )
        work_dir = Path(temp_dir) / "publish"
        result = launcher.create_adspower_plan(plan_args(root), work_dir)
        assert result["videos"] == 2
        assert result["profiles"] == ["27", "28"]
        assert result["next_state"] == "publish-review"

        with Path(result["plan"]).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["环境编号"] for row in rows] == ["27", "28"]
        assert [row["商品PID"] for row in rows] == ["123456", "789012"]
        assert [row["预定时间"] for row in rows] == ["2026-08-04 10:30", "2026-08-04 11:00"]
        assert "商品 123456 第 1 条 123456.mp4" == rows[0]["文案"]
        assert all("bad.mp4" not in row["视频路径"] for row in rows)
        assert result["mappings"] == [
            {
                "video": str((video_dir / "123456.mp4").resolve()),
                "pid": "123456",
                "profile": "27",
                "scheduled_at": "2026-08-04 10:30",
            },
            {
                "video": str((video_dir / "789012.mp4").resolve()),
                "pid": "789012",
                "profile": "28",
                "scheduled_at": "2026-08-04 11:00",
            },
        ]


def test_bare_hashtags_option_is_treated_as_an_empty_value():
    launcher = load_launcher()
    parser = launcher.build_adspower_parser()
    args = parser.parse_args(
        [
            "plan",
            "--video-root", "videos",
            "--profile-no", "2",
            "--start-at", "2026-08-05 17:00",
            "--hashtags",
            "--timezone", "Asia/Shanghai",
        ]
    )
    assert args.hashtags == ""
    assert args.timezone == "Asia/Shanghai"


def test_fake_mp4_is_rejected_before_a_publish_plan_is_created():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "videos"
        root.mkdir()
        (root / "fake.mp4").write_bytes(b"\x89PNG\r\n\x1a\nimage-content")
        try:
            launcher.create_adspower_plan(plan_args(root), Path(temp_dir) / "publish")
        except ValueError as exc:
            assert "No valid generated video" in str(exc)
        else:
            raise AssertionError("A PNG payload renamed to .mp4 entered the publish plan")


def test_non_numeric_pid_is_never_used_for_product_attachment():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "videos"
        write_mp4(root / "lookbook-front.mp4")
        try:
            launcher.create_adspower_plan(plan_args(root, profile_no=["27"]), Path(temp_dir) / "publish")
        except ValueError as exc:
            assert "exact numeric PID" in str(exc)
            assert "lookbook-front" in str(exc)
        else:
            raise AssertionError("A non-numeric PID entered a product-attachment plan")


def test_manifest_pid_must_match_video_filename_before_attachment():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "result"
        text_dir = root / "文本"
        video = root / "视频" / "123456.mp4"
        text_dir.mkdir(parents=True)
        write_mp4(video)
        (text_dir / "record.json").write_text(
            json.dumps({"state": "success", "pid": "999999", "video_path": str(video)}),
            encoding="utf-8",
        )
        try:
            launcher.create_adspower_plan(plan_args(root), Path(temp_dir) / "publish")
        except ValueError as exc:
            assert "same exact numeric PID" in str(exc)
            assert "123456.mp4 -> 999999" in str(exc)
        else:
            raise AssertionError("A mismatched manifest PID entered a product-attachment plan")


def test_schedule_interval_must_use_half_hour_steps():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "videos"
        write_mp4(root / "123456.mp4")
        try:
            launcher.create_adspower_plan(
                plan_args(root, interval_minutes=45),
                Path(temp_dir) / "publish",
            )
        except ValueError as exc:
            assert "multiple of 30 minutes" in str(exc)
        else:
            raise AssertionError("A non-half-hour schedule interval was accepted")


def test_csv_plan_is_safely_parsed_into_preview_and_publish_tasks():
    launcher = load_launcher()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video = root / "123456.mp4"
        write_mp4(video)
        plan = root / "schedule.csv"
        with plan.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["启用", "环境编号", "视频路径", "文案", "标签", "商品PID", "预定时间", "发布模式"])
            writer.writerow(["yes", "27", str(video), "男装", "#TikTokShop", "123456", "2026-08-04 10:30", "schedule"])
        preview_path = root / "preview.json"
        publish_path = root / "publish.json"
        launcher.prepare_adspower_tasks(plan, preview_path, "preview")
        launcher.prepare_adspower_tasks(plan, publish_path, "publish")
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        publish = json.loads(publish_path.read_text(encoding="utf-8"))
        assert preview[0]["publish"] is False
        assert publish[0]["publish"] is True
        assert publish[0]["productPid"] == "123456"
        assert publish[0]["description"] == "男装 #TikTokShop"


def test_xlsx_plan_uses_the_safe_python_parser():
    launcher = load_launcher()
    from openpyxl import Workbook

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video = root / "654321.mp4"
        write_mp4(video)
        plan = root / "schedule.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "发布计划"
        sheet.append(["启用", "环境编号", "视频路径", "商品PID", "预定时间", "发布模式"])
        sheet.append(["yes", "31", str(video), "654321", "2026-08-04 12:00", "schedule"])
        workbook.save(plan)
        output = root / "tasks.json"
        launcher.prepare_adspower_tasks(plan, output, "preview")
        tasks = json.loads(output.read_text(encoding="utf-8"))
        assert tasks[0]["profileNo"] == "31"
        assert tasks[0]["productPid"] == "654321"
        assert tasks[0]["publish"] is False


def test_formal_publish_requires_exact_fabu_before_node_starts():
    launcher = load_launcher()
    args = SimpleNamespace(publish_code="wrong", input_file="", visible=False)
    try:
        launcher.execute_adspower_plan(
            "publish",
            args,
            Path("node"),
            Path("publish"),
            {"schedule": "schedule.csv", "config": "config.json"},
        )
    except ValueError as exc:
        assert "FABU" in str(exc)
    else:
        raise AssertionError("Formal publishing started without FABU")


def test_ads_runtime_uses_adspower_checks_and_per_profile_reports():
    checker = (PLUGIN_ROOT / "scripts" / "adspower_runtime" / "src" / "tiktok-checker.mjs").read_text(encoding="utf-8")
    publisher = (PLUGIN_ROOT / "scripts" / "adspower_runtime" / "src" / "publisher.mjs").read_text(encoding="utf-8")
    cli = (PLUGIN_ROOT / "scripts" / "adspower_runtime" / "src" / "cli.mjs").read_text(encoding="utf-8")
    assert "new AdsPowerClient(config.adspower)" in checker
    assert "checkTikTokUploadWindows" in cli
    assert "return [...preflightResults, ...groupResults.flat()]" in publisher
    assert "task.resolveError" in publisher
    assert "requiresManualTakeover" in publisher
    assert "waitForTikTokUploadInput" in publisher
    assert "dismissTikTokTours" in publisher
    assert "TikTok login required in this AdsPower profile" in publisher
    launcher_source = (PLUGIN_ROOT / "scripts" / "h_run.py").read_text(encoding="utf-8")
    assert 'tasks_path = work_dir / "tasks" / f"{command}-{stamp}.json"' in launcher_source
    assert "process.exitCode = 2" in cli
    assert "args.report" in cli


def run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} AdsPower pipeline tests")


if __name__ == "__main__":
    run_all()
