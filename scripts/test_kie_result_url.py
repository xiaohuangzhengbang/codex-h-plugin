import importlib.util
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

    dirty = "\ufeff\u200b747c2c821e525aef75929877cc81354b\u200d\n"
    clean = "747c2c821e525aef75929877cc81354b"

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
    veo_reference = batch.veo_input_payload("veo3.1-quality", "prompt", ["a.png", "b.png", "c.png"], "16:9", "720p")
    assert veo_reference["generationType"] == "REFERENCE_2_VIDEO"
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
    print("kie_result_url regression tests passed")
