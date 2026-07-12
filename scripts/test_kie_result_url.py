import importlib.util
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).with_name("kie_video_batch.py")


def load_batch_module():
    spec = importlib.util.spec_from_file_location("kie_video_batch_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.load_api_key = lambda explicit: module.clean_api_key(explicit)
    return module


def test_kie_result_url_prefers_result_json_over_param():
    batch = load_batch_module()
    original_url = "https://tempfile.redpandaai.co/original/source.webp"
    generated_url = "https://tempfile.aiquickdraw.com/images/chatgpt/generated.png"
    data = {
        "param": f'{{"input_urls":["{original_url}"]}}',
        "resultJson": f'{{"resultUrls":["{generated_url}"]}}',
    }

    assert batch.kie_result_url(data, "image") == generated_url


def test_kie_result_url_ignores_input_fallback_when_result_json_exists():
    batch = load_batch_module()
    original_url = "https://tempfile.redpandaai.co/original/source.webp"
    generated_url = "https://tempfile.aiquickdraw.com/images/chatgpt/generated.png"
    data = {
        "input": {"image": original_url},
        "resultJson": {"resultUrls": [generated_url]},
    }

    assert batch.kie_result_url(data, "image") == generated_url


def test_kie_result_url_prefers_veo_response_video_over_param_json_image():
    batch = load_batch_module()
    source_url = "https://tempfile.redpandaai.co/kieai/product-video/source.png"
    video_url = "https://tempfile.aiquickdraw.com/v/task_123.mp4"
    data = {
        "paramJson": f'{{"imageUrls":["{source_url}"]}}',
        "response": {"resultUrls": [video_url]},
    }

    assert batch.kie_result_url(data, "video") == video_url


def test_video_result_url_does_not_fallback_to_image_reference():
    batch = load_batch_module()
    source_url = "https://tempfile.redpandaai.co/kieai/product-video/source.png"
    data = {
        "paramJson": f'{{"imageUrls":["{source_url}"]}}',
        "response": {"resultUrls": [source_url]},
    }

    assert batch.kie_result_url(data, "video") == ""


def test_video_file_validation_rejects_png_saved_as_mp4():
    batch = load_batch_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "bad.mp4"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        try:
            batch.validate_downloaded_file(path, "video", "https://example.com/source.png")
        except RuntimeError as exc:
            assert "not a valid video" in str(exc)
        else:
            raise AssertionError("Expected PNG content saved as .mp4 to be rejected")
        assert not path.exists()


def test_image_scheduler_runs_all_root_items_in_one_concurrent_pool():
    batch = load_batch_module()
    starts = []
    original = batch.process_single_product

    def fake_process_single_product(args, folder, output_dir, text_dir, product, image_model_label, image_model, aspect_ratio):
        starts.append((product.pid, time.perf_counter()))
        time.sleep(0.2)
        return {"pid": product.pid, "folder": folder.name, "state": "success"}

    batch.process_single_product = fake_process_single_product
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder_a = root / "folder-a"
            folder_b = root / "folder-b"
            folder_a.mkdir()
            folder_b.mkdir()
            folders = [
                batch.ProductFolder(
                    "folder-a",
                    folder_a,
                    [
                        batch.ProductImage("a1", folder_a / "a1.png"),
                        batch.ProductImage("a2", folder_a / "a2.png"),
                    ],
                ),
                batch.ProductFolder(
                    "folder-b",
                    folder_b,
                    [
                        batch.ProductImage("b1", folder_b / "b1.png"),
                        batch.ProductImage("b2", folder_b / "b2.png"),
                    ],
                ),
            ]
            args = SimpleNamespace(workers=0, output_dir="")

            batch.process_product_folders_concurrently(args, folders, root, True, "label", "model", "9:16")

        assert len(starts) == 4
        assert max(start for _pid, start in starts) - min(start for _pid, start in starts) < 0.15
        assert {pid for pid, _start in starts} == {"a1", "a2", "b1", "b2"}
    finally:
        batch.process_single_product = original


def test_default_output_layout_uses_desktop_text_image_video_dirs():
    batch = load_batch_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "产品根"
        folder = batch.ProductFolder("folder-a", root / "folder-a", [])
        args = SimpleNamespace(output_dir="")
        image_dir = batch.process_output_dir(args, root, folder, True)
        text_dir = batch.process_text_output_dir(args, root, folder, True)
        video_dir = batch.video_output_dir(args, root, folder, True)

        assert image_dir.parts[-2:] == ("图像", "folder-a")
        assert text_dir.parts[-2:] == ("文本", "folder-a")
        assert video_dir.parts[-2:] == ("视频", "folder-a")
        assert "H返回结果_产品根" in str(image_dir)


def test_user_secret_precedes_plugin_local_for_any_secret():
    batch = load_batch_module()
    assert batch.choose_secret(
        [
            ("explicit", ""),
            ("env", ""),
            ("user_secret", "sk-user-secret"),
            ("plugin_local", "sk-plugin-local"),
        ],
        "generic",
    ) == "sk-user-secret"


def test_kie_user_secret_precedes_plugin_local_key():
    batch = load_batch_module()
    assert batch.choose_secret(
        [
            ("--api-key", ""),
            ("H_KIE_API_KEY", ""),
            ("KIE_API_KEY", ""),
            ("user_secret", "kie-user-secret"),
            ("plugin_local", "kie-plugin-local"),
        ],
        "Kie",
    ) == "kie-user-secret"


def test_api_key_cleaning_removes_bom_and_hidden_chars_from_headers():
    batch = load_batch_module()

    dirty = "\ufeff\u200btest-kie-key-000000000000000000000000\u200d\n"
    clean = "test-kie-key-000000000000000000000000"

    assert batch.clean_api_key(dirty) == clean
    assert batch.get_headers(dirty)["Authorization"] == f"Bearer {clean}"
    assert batch.choose_secret([("user_secret", dirty)], "Kie") == clean


def test_default_reverse_model_is_gpt_5_5():
    batch = load_batch_module()
    args = batch.parse_args(
        [
            "process-images",
            ".",
            "--api-key",
            "test-key",
            "--image-reverse-meta-prompt",
            "Prompt for {pid}",
        ]
    )

    assert args.reverse_model == "gpt-5-5"


def test_response_output_text_extracts_kie_responses_text():
    batch = load_batch_module()
    data = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "final prompt"}
                ],
            },
        ]
    }

    assert batch.response_output_text(data) == "final prompt"


def test_gpt_image_2_text_payload_has_no_source_image_field():
    batch = load_batch_module()
    payload = batch.image_input_payload(
        "gpt-image-2-text-to-image",
        "prompt",
        "https://example.com/source.png",
        "16:9",
        "1K",
    )

    assert payload == {"prompt": "prompt", "aspect_ratio": "16:9"}


def test_gpt_image_2_image_payload_uses_input_urls():
    batch = load_batch_module()
    payload = batch.image_input_payload(
        "gpt-image-2-image-to-image",
        "prompt",
        "https://example.com/source.png",
        "9:16",
        "1K",
    )

    assert payload["input_urls"] == ["https://example.com/source.png"]
    assert "image_urls" not in payload


def test_seedance_video_payload_uses_first_frame_url_and_model_controls():
    batch = load_batch_module()
    payload = batch.video_input_payload(
        "bytedance/seedance-2",
        "prompt",
        "https://example.com/frame.png",
        "16:9",
        "720p",
        6,
    )

    assert payload["first_frame_url"] == "https://example.com/frame.png"
    assert payload["resolution"] == "720p"
    assert payload["aspect_ratio"] == "16:9"
    assert payload["duration"] == 6
    assert payload["generate_audio"] is False
    assert payload["web_search"] is False


def test_video_payloads_route_media_counts_by_model():
    batch = load_batch_module()

    assert batch.veo_input_payload("veo3.1-lite", "prompt", [], "16:9", "720p")["generationType"] == "TEXT_2_VIDEO"
    veo_first_last = batch.veo_input_payload("veo3.1-fast", "prompt", ["first.png", "last.png"], "16:9", "720p")
    assert veo_first_last["generationType"] == "FIRST_AND_LAST_FRAMES_2_VIDEO"
    assert veo_first_last["imageUrls"] == ["first.png", "last.png"]
    veo_reference = batch.veo_input_payload("veo3.1-lite", "prompt", ["a.png", "b.png", "c.png"], "16:9", "720p")
    assert veo_reference["generationType"] == "REFERENCE_2_VIDEO"
    assert "resolution" not in veo_reference
    try:
        batch.veo_input_payload("veo3.1-quality", "prompt", ["a.png", "b.png", "c.png"], "16:9", "720p")
    except ValueError as exc:
        assert "Quality does not support" in str(exc)
    else:
        raise AssertionError("Expected Veo Quality to reject 3-image reference mode")
    try:
        batch.veo_input_payload("veo3.1-lite", "prompt", ["1.png", "2.png", "3.png", "4.png"], "16:9", "720p")
    except ValueError as exc:
        assert "more than 3 images" in str(exc)
    else:
        raise AssertionError("Expected Veo to reject more than 3 images")

    try:
        batch.video_input_payload("grok-imagine/image-to-video", "prompt", ["a.png", "b.png"], "16:9", "720p", 6)
    except ValueError as exc:
        assert "exactly 1 image" in str(exc)
    else:
        raise AssertionError("Expected Grok to reject more than 1 image")

    seedance_last = batch.video_input_payload("bytedance/seedance-2", "prompt", ["first.png", "last.png"], "16:9", "720p", 6)
    assert seedance_last["first_frame_url"] == "first.png"
    assert seedance_last["last_frame_url"] == "last.png"
    seedance_reference = batch.video_input_payload(
        "bytedance/seedance-2",
        "prompt",
        ["a.png", "b.png", "c.png"],
        "16:9",
        "720p",
        6,
        video_urls=["ref.mp4"],
        audio_urls=["ref.mp3"],
    )
    assert seedance_reference["reference_image_urls"] == ["a.png", "b.png", "c.png"]
    assert seedance_reference["reference_video_urls"] == ["ref.mp4"]
    assert seedance_reference["reference_audio_urls"] == ["ref.mp3"]


def test_gemini_omni_payload_does_not_receive_unsupported_resolution_fields():
    batch = load_batch_module()
    payload = batch.video_input_payload(
        "gemini-omni-video",
        "prompt",
        "https://example.com/frame.png",
        "16:9",
        "720p",
        6,
    )

    assert payload == {
        "prompt": "prompt",
        "image_urls": ["https://example.com/frame.png"],
        "duration": "6",
    }


def test_reverse_model_aliases_are_normalized_to_kie_ids():
    batch = load_batch_module()

    assert batch.normalize_reverse_model("1") == "gpt-5-5"
    assert batch.normalize_reverse_model("2") == "gpt-5-4"
    assert batch.normalize_reverse_model("3") == "gemini-3.1-pro"
    assert batch.normalize_reverse_model("4") == "gemini-3-pro"
    assert batch.normalize_reverse_model("5") == "gemini-3-5-flash-openai"
    assert batch.normalize_reverse_model("6") == "gemini-3-flash"
    assert batch.normalize_reverse_model("gemini-3.5-flash") == "gemini-3-5-flash-openai"
    assert batch.normalize_reverse_model("gpt-5-5") == "gpt-5-5"


def test_image_model_family_resolves_endpoint_from_image_presence():
    batch = load_batch_module()

    assert batch.resolve_image_generation_model("gpt-image-2", True) == "gpt-image-2-image-to-image"
    assert batch.resolve_image_generation_model("gpt-image-2", False) == "gpt-image-2-text-to-image"
    assert batch.resolve_image_generation_model("seedream/5-lite", True) == "seedream/5-lite-image-to-image"
    assert batch.resolve_image_generation_model("seedream/5-lite", False) == "seedream/5-lite-text-to-image"


def test_video_model_family_resolves_endpoint_from_image_presence():
    batch = load_batch_module()

    assert batch.resolve_video_generation_model("grok-imagine", True) == "grok-imagine/image-to-video"
    assert batch.resolve_video_generation_model("grok-imagine", False) == "grok-imagine/text-to-video"
    assert batch.resolve_video_generation_model("gemini-omni-video", True) == "gemini-omni-video"


def test_seedance_video_payload_omits_frame_when_no_image_is_present():
    batch = load_batch_module()
    payload = batch.video_input_payload(
        "bytedance/seedance-2",
        "prompt",
        "",
        "16:9",
        "720p",
        6,
    )

    assert "first_frame_url" not in payload
    assert payload["prompt"] == "prompt"
    assert payload["duration"] == 6


def test_image_resolution_numeric_choices_map_to_k_values():
    batch = load_batch_module()

    assert batch.resolve_image_resolution("1") == "1K"
    assert batch.resolve_image_resolution("2") == "2K"
    assert batch.resolve_image_resolution("3") == "4K"


def test_legacy_resolution_argument_maps_to_image_resolution():
    batch = load_batch_module()

    args = batch.parse_args(
        [
            "process-images",
            "input-root",
            "--api-key",
            "test-key",
            "--image-reverse-meta-prompt",
            "prompt",
            "--resolution",
            "3",
        ]
    )

    assert args.image_resolution == "3"


def test_video_duration_defaults_and_rejects_over_model_max():
    batch = load_batch_module()

    assert batch.resolve_video_duration(0, "gemini-omni-video") == 6
    assert batch.resolve_video_duration(30, "gemini-omni-video") == 30
    assert batch.resolve_video_duration(30, "grok-imagine/image-to-video") == 30
    assert batch.resolve_video_duration(0, "veo3.1-lite") == 8
    assert batch.resolve_video_duration(30, "veo3.1-lite") == 8
    assert batch.resolve_video_duration(0, "bytedance/seedance-2") == 6
    assert batch.allowed_video_durations("gemini-omni-video") == [4, 6, 8, 10, 15, 20, 25, 30]
    assert batch.allowed_video_durations("grok-imagine/image-to-video") == [4, 6, 8, 10, 15, 20, 25, 30]
    assert batch.allowed_video_durations("grok-imagine-video-1-5-preview") == [4, 6, 8, 10, 15]
    assert batch.allowed_video_durations("veo3.1-lite") == [8]
    assert batch.allowed_video_durations("bytedance/seedance-2") == [4, 6, 8, 10, 15]
    try:
        batch.resolve_video_duration(30, "grok-imagine-video-1-5-preview")
    except ValueError as exc:
        assert "supports up to 15s" in str(exc)
    else:
        raise AssertionError("Expected Grok 1.5 Preview over-duration to fail")
    try:
        batch.resolve_video_duration(30, "bytedance/seedance-2")
    except ValueError as exc:
        assert "supports up to 15s" in str(exc)
    else:
        raise AssertionError("Expected Seedance over-duration to fail")


def test_image_file_validation_rejects_html_saved_as_png():
    batch = load_batch_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "bad.png"
        path.write_text("<html>provider error</html>", encoding="utf-8")
        try:
            batch.validate_downloaded_file(path, "image", "https://example.com/error")
        except RuntimeError as exc:
            assert "not a valid image" in str(exc)
        else:
            raise AssertionError("Expected HTML saved as .png to be rejected")
        assert not path.exists()


def test_recursive_discovery_preserves_nested_relative_paths():
    batch = load_batch_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "root"
        first = root / "group-a" / "set-1"
        second = root / "group-b"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "PID-A.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        (second / "PID-B.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)

        folders = batch.discover_product_folders(root)

        assert [folder.relative_path.as_posix() for folder in folders] == ["group-a/set-1", "group-b"]
        assert folders[0].output_path.as_posix() == "group-a/set-1"
        assert {image.pid for folder in folders for image in folder.images} == {"PID-A", "PID-B"}


def test_gemini_native_candidate_text_is_supported():
    batch = load_batch_module()
    data = {"candidates": [{"content": {"parts": [{"text": "native Gemini result"}]}}]}
    assert batch.response_output_text(data) == "native Gemini result"


def test_gpt_5_5_provider_failure_falls_back_to_5_4():
    batch = load_batch_module()
    calls = []

    class FakeResponse:
        reason = ""

        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.text = json.dumps(data)

        def json(self):
            return self._data

    responses = [
        FakeResponse(503, {"message": "temporarily unavailable"}),
        FakeResponse(200, {"output_text": "fallback result"}),
    ]

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["json"]["model"]))
        return responses.pop(0)

    batch.request_with_retry = fake_request
    content, raw = batch.text_with_kie("test-key", "gpt-5-5", "prompt")

    assert content == "fallback result"
    assert [call[2] for call in calls] == ["gpt-5-5", "gpt-5-4"]
    assert raw["_h_meta"]["fallback_used"] is True
    assert raw["_h_meta"]["actual_model"] == "gpt-5-4"


def test_gpt_5_5_authentication_failure_does_not_fallback():
    batch = load_batch_module()
    calls = []

    class FakeResponse:
        status_code = 401
        text = '{"message":"invalid key"}'
        reason = "Unauthorized"

        def json(self):
            return {"message": "invalid key"}

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["json"]["model"]))
        return FakeResponse()

    batch.request_with_retry = fake_request
    try:
        batch.text_with_kie("bad-key", "gpt-5-5", "prompt")
    except batch.KieAPIError as exc:
        assert exc.category == "authentication"
    else:
        raise AssertionError("Expected authentication failure")
    assert [call[2] for call in calls] == ["gpt-5-5"]


def test_thread_local_session_keeps_tls_verification_enabled():
    batch = load_batch_module()
    session = batch.new_session()
    assert session.verify is True


def test_gemini_omni_video_payload_uses_documented_video_object_and_quota():
    batch = load_batch_module()
    payload = batch.video_input_payload(
        "gemini-omni-video",
        "prompt",
        ["one.png", "two.png"],
        "16:9",
        "720p",
        4,
        video_urls=["ref.mp4"],
        audio_ids=["audio-1"],
        character_ids=["char-1", "char-2"],
    )
    assert payload["video_list"] == [{"url": "ref.mp4", "start": 0, "ends": 10}]
    assert payload["audio_ids"] == ["audio-1"]
    assert payload["character_ids"] == ["char-1", "char-2"]
    try:
        batch.video_input_payload(
            "gemini-omni-video",
            "prompt",
            ["1", "2", "3", "4"],
            "16:9",
            "720p",
            4,
            video_urls=["ref.mp4"],
            character_ids=["a", "b"],
        )
    except ValueError as exc:
        assert "quota exceeded" in str(exc)
    else:
        raise AssertionError("Expected Gemini Omni quota overflow to fail")


def test_saved_image_task_is_resumed_without_upload_or_resubmit():
    batch = load_batch_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "PID-1.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        output_dir = root / "out"
        text_dir = root / "text"
        text_dir.mkdir()
        reverse_prompt = "saved reverse prompt"
        reverse_path = text_dir / "PID-1.reverse.txt"
        reverse_path.write_text(reverse_prompt, encoding="utf-8")
        args = SimpleNamespace(
            force=False,
            reverse_model="gpt-5-5",
            reverse_api="auto",
            reverse_reasoning_effort="high",
            image_reverse_meta_prompt="meta {pid}",
            prompt="extra",
            image_resolution="1",
            image_model="1",
            api_key="test-key",
            timeout=1,
            poll=1,
            max_query_errors=1,
        )
        source_digest = batch.file_sha256(source)
        reverse_signature = batch.stable_hash(
            {
                "version": 2,
                "source_sha256": source_digest,
                "model": "gpt-5-5",
                "api": "auto",
                "reasoning": "high",
                "meta_prompt": "meta {pid}",
            }
        )
        prompt = batch.build_kie_image_prompt(reverse_prompt, "PID-1", "extra")
        generation_signature = batch.stable_hash(
            {
                "version": 2,
                "reverse_signature": reverse_signature,
                "reverse_prompt": reverse_prompt,
                "model": "gpt-image-2-image-to-image",
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "resolution": "1K",
            }
        )
        record_path = text_dir / "PID-1.image.json"
        record_path.write_text(
            json.dumps(
                {
                    "pid": "PID-1",
                    "state": "timeout",
                    "task_id": "saved-task-id",
                    "query_type": "jobs",
                    "source_url": "https://example.com/source.png",
                    "reverse_signature": reverse_signature,
                    "generation_signature": generation_signature,
                }
            ),
            encoding="utf-8",
        )
        batch.upload_file = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upload must not run"))
        batch.submit_job = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit must not run"))
        batch.wait_for_result = lambda *_args, **_kwargs: (
            "success",
            "https://example.com/generated.png",
            {"data": {"state": "success"}},
        )

        def fake_download(_url, path, _kind):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        batch.download_file = fake_download
        folder = batch.ProductFolder("root", root, [batch.ProductImage("PID-1", source)])
        record = batch.process_single_product(
            args,
            folder,
            output_dir,
            text_dir,
            batch.ProductImage("PID-1", source),
            "GPT Image-2",
            "gpt-image-2",
            "16:9",
        )

        assert record["state"] == "success"
        assert record["task_id"] == "saved-task-id"
        assert batch.is_image_file(output_dir / "PID-1.png")


def test_catalog_lists_all_models_without_a_key_and_includes_follow_up_actions():
    batch = load_batch_module()
    args = batch.parse_args(["catalog"])
    catalog = batch.model_catalog()
    assert args.command == "catalog"
    assert len(catalog["text"]) == 6
    assert len(catalog["image"]) == 6
    assert {item["model"] for item in catalog["video"]} >= {"grok-imagine/upscale", "grok-imagine/extend"}
    assert batch.next_actions("images")[0]["action"] == "继续生成视频"
    assert "不重复提交" in batch.next_actions("single")[0]["action"]


def test_repository_test_data_contains_no_key_shaped_literal():
    source = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", source)
    old_key = "747c2c82" + "1e525aef" + "75929877" + "cc81354b"
    assert old_key not in source


def test_single_image_without_media_routes_to_text_to_image_and_writes_three_folders():
    batch = load_batch_module()
    submitted = {}

    def fake_submit(_api_key, model, payload):
        submitted["model"] = model
        submitted["payload"] = payload
        return "single-task", {"code": 200, "data": {"taskId": "single-task"}}

    batch.submit_job = fake_submit
    batch.wait_for_result = lambda *_args, **_kwargs: (
        "success",
        "https://example.com/generated.png",
        {"data": {"state": "success"}},
    )

    def fake_download(_url, path, _kind):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    batch.download_file = fake_download
    with tempfile.TemporaryDirectory() as temp_dir:
        args = SimpleNamespace(
            kind="image",
            model="1",
            prompt="a product image",
            media=[],
            video_ref=[],
            audio_ref=[],
            audio_id=[],
            character_id=[],
            source_task_id="",
            extend_at=2,
            extend_times=1,
            aspect_ratio="2",
            image_resolution="1",
            video_resolution="720p",
            duration=0,
            reasoning_effort="high",
            api_key="test-key",
            timeout=1,
            poll=1,
            max_query_errors=1,
            preflight_timeout=1,
            skip_preflight=True,
            output_dir=temp_dir,
        )
        code = batch.single_call(args)
        root = Path(temp_dir)
        records = list((root / "文本").glob("*.json"))

        assert code == 0
        assert submitted["model"] == "gpt-image-2-text-to-image"
        assert "input_urls" not in submitted["payload"]
        assert (root / "图像").is_dir() and (root / "视频").is_dir()
        assert len(records) == 1
        record = json.loads(records[0].read_text(encoding="utf-8"))
        assert record["state"] == "success"
        assert record["next_actions"][0]["action"].startswith("重试或继续")


def test_veo_1080p_uses_dedicated_result_endpoint():
    batch = load_batch_module()

    class FakeResponse:
        status_code = 200
        text = '{"code": 200}'
        reason = ""

        def json(self):
            return {
                "code": 200,
                "msg": "success",
                "data": {"resultUrl": "https://example.com/1080.mp4"},
            }

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["params"]))
        return FakeResponse()

    batch.request_with_retry = fake_request
    result_url, raw = batch.ensure_veo_resolution(
        "test-key",
        "veo-task",
        "1080p",
        "https://example.com/initial.mp4",
        {"data": {"response": {"resolution": "720p"}}},
        10,
        1,
    )

    assert result_url == "https://example.com/1080.mp4"
    assert raw["data"]["resultUrl"] == result_url
    assert calls[0][0] == "GET"
    assert calls[0][1].endswith("/api/v1/veo/get-1080p-video")
    assert calls[0][2] == {"taskId": "veo-task", "index": 0}


if __name__ == "__main__":
    test_kie_result_url_prefers_result_json_over_param()
    test_kie_result_url_ignores_input_fallback_when_result_json_exists()
    test_kie_result_url_prefers_veo_response_video_over_param_json_image()
    test_video_result_url_does_not_fallback_to_image_reference()
    test_video_file_validation_rejects_png_saved_as_mp4()
    test_image_scheduler_runs_all_root_items_in_one_concurrent_pool()
    test_default_output_layout_uses_desktop_text_image_video_dirs()
    test_user_secret_precedes_plugin_local_for_any_secret()
    test_kie_user_secret_precedes_plugin_local_key()
    test_api_key_cleaning_removes_bom_and_hidden_chars_from_headers()
    test_default_reverse_model_is_gpt_5_5()
    test_response_output_text_extracts_kie_responses_text()
    test_gpt_image_2_text_payload_has_no_source_image_field()
    test_gpt_image_2_image_payload_uses_input_urls()
    test_seedance_video_payload_uses_first_frame_url_and_model_controls()
    test_video_payloads_route_media_counts_by_model()
    test_gemini_omni_payload_does_not_receive_unsupported_resolution_fields()
    test_reverse_model_aliases_are_normalized_to_kie_ids()
    test_image_model_family_resolves_endpoint_from_image_presence()
    test_video_model_family_resolves_endpoint_from_image_presence()
    test_seedance_video_payload_omits_frame_when_no_image_is_present()
    test_image_resolution_numeric_choices_map_to_k_values()
    test_legacy_resolution_argument_maps_to_image_resolution()
    test_video_duration_defaults_and_rejects_over_model_max()
    test_image_file_validation_rejects_html_saved_as_png()
    test_recursive_discovery_preserves_nested_relative_paths()
    test_gemini_native_candidate_text_is_supported()
    test_gpt_5_5_provider_failure_falls_back_to_5_4()
    test_gpt_5_5_authentication_failure_does_not_fallback()
    test_thread_local_session_keeps_tls_verification_enabled()
    test_gemini_omni_video_payload_uses_documented_video_object_and_quota()
    test_saved_image_task_is_resumed_without_upload_or_resubmit()
    test_catalog_lists_all_models_without_a_key_and_includes_follow_up_actions()
    test_repository_test_data_contains_no_key_shaped_literal()
    test_single_image_without_media_routes_to_text_to_image_and_writes_three_folders()
    test_veo_1080p_uses_dedicated_result_endpoint()
    print("kie_result_url regression tests passed")
