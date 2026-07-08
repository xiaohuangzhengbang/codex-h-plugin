---
name: h
description: Pure Kie batch workflow for PID-named product folders. Use when the user gives product-image folders and wants every original product image reverse-prompted by Kie multimodal text models, then generated as images/videos through Kie with whole-root concurrency.
---

# H

H is a pure Kie batch workflow. It submits all eligible PID items under the whole input root concurrently. Subfolders are only used to preserve output organization; they must not serialize generation.

When H is invoked, the first user-visible chat message must begin with:

```text
哈喽小杨，你又开始工作啦，想不想小黄啊？
```

This greeting must be sent in the chat itself, not only printed by the Python launcher, because Codex may summarize or hide tool stdout.

Default workflow:

1. Original product image -> Kie GPT 5.5/5.4 or Gemini multimodal reverse prompt -> Kie image generation.
2. Generated product image -> Kie GPT 5.5/5.4 or Gemini multimodal reverse video prompt -> Kie video generation.

Each PID is independent. Never reuse one reversed prompt across different products.

## Hard Rules

1. Do not call any non-Kie provider. All reverse prompting, image generation, and video generation must stay inside Kie.
2. Default reverse model is `gpt-5-5`; fallback is `gpt-5-4`.
3. Gemini reverse models are allowed only through Kie OpenAI-compatible chat endpoints.
4. Submit every eligible PID under the whole input root concurrently. If one image takes about 3 minutes, ten images should be submitted together and finish in roughly the same generation window, subject to provider limits.
5. Save each reverse prompt immediately after reverse succeeds and before generation submission. Reruns must reuse saved `.reverse.txt` / `.video_reverse.txt`.
6. Result parsing must prefer `resultJson` / `resultUrls`. Never save `param`, `input`, `input_urls`, uploaded source URLs, or original CDN URLs as generated outputs.
7. If a resolved image result URL equals the uploaded source URL, fail that PID instead of saving a false success.
8. A forced rerun must remove stale PID output files, reverse prompt text, and JSON record before regeneration.
9. Model request payloads are model-specific. Do not reuse one image/video payload shape across all models.
10. User-facing model selection must list all available choices by number. Do not say only "recommended 1" or hide the rest of the model list.
11. Always run the workflow through `python scripts/h_run.py`, not directly through `python scripts/kie_video_batch.py`. The launcher creates a plugin-local Python environment and installs `requirements.txt` quietly.
12. If a historical command uses `--resolution`, keep it working by treating it as `--image-resolution`; do not stop the workflow to explain the rename.
13. Do not print long dependency-install logs unless dependency setup fails. On success, continue directly to the requested batch/single processing.
14. On the first H use in a plugin directory or on a new computer, run `python scripts/h_run.py --doctor` before asking for processing parameters. If `.h_ready.json` exists and is current for this plugin directory, skip the doctor step.

## Runtime Requirements

H must verify these requirements once during first load/bootstrap:

- Python 3.10+ available to Codex.
- Python `venv` module available.
- Network access for installing `requirements.txt` if the plugin-local `.h_venv` does not already exist.
- Runtime dependency: `requests>=2.32,<3`.
- Kie API key from `--api-key`, `H_KIE_API_KEY`, `KIE_API_KEY`, `<home>/.codex/secrets/h_kie_api_key.txt`, or plugin-local `.h_api_key`.
- Writable plugin directory for `.h_venv` and `.h_ready.json`.
- Writable Desktop output directory.

First-load bootstrap command:

```bash
python scripts/h_run.py --doctor
```

If doctor succeeds, do not show dependency setup details to the user again. If doctor fails, report only the failed requirement and the short fix.

## Folder Model

Input can be:

```text
root/
  project-A/
    PID001.png
    PID002.png
  project-B/
    PID003.png
    PID004.png
```

Stage 1 writes:

```text
Desktop/
  H返回结果_root/
    文本/
      project-A/
        PID001.reverse.txt
        PID001.image.json
        processed_manifest.json
      h_processed_batch_manifest.json
    图像/
      project-A/
        PID001.png
    视频/
```

Stage 2 writes:

```text
Desktop/
  H返回结果_root/
    文本/
      project-A/
        PID001.video_reverse.txt
        PID001.video.json
        video_manifest.json
      h_video_batch_manifest.json
    图像/
      project-A/
        PID001.png
    视频/
      project-A/
        PID001.mp4
```

If the input folder directly contains PID images, treat that folder as one project.

If `--output-dir` is not provided, H must automatically create the result folder on the user's Desktop. This must work on Windows, macOS Intel, and macOS Apple Silicon:

```text
<home>/Desktop/H返回结果_<input-folder-name>/
  文本/
  图像/
  视频/
```

If `--output-dir` is provided, H must still create the same three subfolders inside that output directory.

## Required Interaction

H has exactly two user-facing entry modes and the first prompt must show only these two choices:

```text
请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
```

Do not explain the mode choice as "give me a folder path or give me model + prompt". Do not ask for model parameters before the user has chosen `批处理` or `单处理`.

Internal routing:

- `批处理`: process a folder/root path and all eligible files under it.
- `单处理`: call one selected Kie model once with one prompt and the supplied media.

Do not mix the two modes. If the user explicitly says batch/all/folder/root, use `批处理`. If the user explicitly says single/one model/try one model, use `单处理`. If unclear, ask only the two-mode prompt above.

In `单处理`:

1. Do not scan the whole folder as product batches.
2. Do not ask for batch workers, PID folder layout, mannequin/product batch prompts, or folder-wide reverse prompts unless the user explicitly asks for them.
3. Ask only for the selected model, task type if needed, prompt, media files/URLs, aspect ratio/resolution/duration fields supported by that model, and output folder.
4. Apply the same model-specific payload and media-count rules as folder batch mode.
5. Save the returned result under the Desktop output root in the matching `文本`, `图像`, or `视频` folder.
6. If the user provides one local folder only as a convenient media container for the single call, treat its files as that single model call's media inputs, not as PID batch items.

In `批处理`:

1. Confirm H will process all PID images under the whole input root concurrently.
2. Ask for image model, image resolution, and image aspect ratio in one combined prompt. The user must be able to answer all three together, for example `1 1 2` = model 1, resolution 1K, ratio 16:9. Do not split these into separate turns unless the user explicitly asks.
3. Validate that image model, resolution, and aspect ratio are all selected before asking any reverse model or prompt. If one value is missing, ask only for the missing value.
4. The default may be shown only as "直接回车：使用默认 1 1 2".
5. Ask for image reverse text model by listing every available reverse model choice with its number. Do not silently use the default unless the user presses Enter.
6. Ask for image reverse meta prompt. The default prompt must be Chinese and may be shown only as "直接回车：使用默认：将每张产品图片反推为详细的 Kie 图片生成提示词。PID：{pid}".
7. Run `process-images` on the root folder using the selected image reverse model via `--reverse-model`.
8. After all processed images complete, ask whether to generate videos.
9. If yes, ask for video model by listing every available video model choice with its number. Include maximum supported duration only when the maximum is confirmed, otherwise say the duration follows Kie's current model support. Do not present one model as the recommendation.
10. Ask for video duration. Filter choices only when the selected model has a confirmed maximum duration; do not treat documentation examples as maximums.
11. Ask for video aspect ratio by listing every available ratio choice with its number.
12. Ask for video reverse text model by listing every available reverse model choice with its number. Do not silently reuse the image reverse model unless the user presses Enter.
13. Ask for video reverse meta prompt. The default prompt must be Chinese and may be shown only as "直接回车：使用默认：将这张处理后的产品图片反推为 Kie 视频生成提示词。PID：{pid}".
14. Run `generate-videos` on the same root folder or processed root using the selected video reverse model via `--reverse-model`. When the same original root is passed, H should automatically find `Desktop/H返回结果_<input-folder-name>/图像`.
15. Return the Desktop/output root plus the `文本`, `图像`, and `视频` folders and generated file paths.

Model/radio prompt format must be explicit and enumerable. For image generation, always use the combined image parameter prompt. Do not ask image model alone.

Reverse text model prompt format must be shown before image reverse meta prompt and before video reverse meta prompt:

```text
请选择反推文本模型，回复编号即可：
1. GPT 5.5 response
2. GPT 5.4 response
3. Gemini 3.1 Pro
4. Gemini 3 Pro
5. Gemini 3.5 Flash
6. Gemini 3 Flash
直接回车：使用默认 1
```

```text
请选择图片模型，回复编号即可：
1. GPT Image-2
2. Nano Banana
3. Nano Banana Pro
4. Nano Banana 2
5. Nano Banana 2 Lite
6. Seedream 5.0 Lite
直接回车：使用默认 1
```

Image resolution prompt format:

```text
请选择图片分辨率，回复编号即可：
1. 1K
2. 2K
3. 4K
直接回车：使用默认 1K
```

Current correct image resolution and aspect prompts. These two prompts are mandatory after image model selection:

```text
请选择图片参数，按顺序回复：图片模型 分辨率 比例

图片模型：
1. GPT Image-2
2. Nano Banana
3. Nano Banana Pro
4. Nano Banana 2
5. Nano Banana 2 Lite
6. Seedream 5.0 Lite

分辨率：
1. 1K
2. 2K
3. 4K

比例：
1. 9:16
2. 16:9

示例：1 1 2
直接回车：使用默认 1 1 2
```

Bad interaction pattern:

```text
图片模型：推荐 1 = GPT Image-2 image-to-image
1. GPT Image-2 image-to-image
2. GPT Image-2 text-to-image
```

Video model prompt format must also list model families, not raw text/image endpoints. Do not write example durations as maximums unless the docs explicitly confirm the max:

Current correct video model list:

```text
请选择视频模型，回复编号即可：
1. Grok Imagine（最长 30s；0 图文生，1 图图生）
2. Grok Imagine Video 1.5 Preview（最长 15s；仅支持 0-1 图）
3. Veo3.1 Lite（固定约 8s；支持 0 图、1-2 图、3 图）
4. Veo3.1 Fast（固定约 8s；支持 0 图、1-2 图、3 图）
5. Veo3.1 Quality（固定约 8s；支持 0 图、1-2 图；参考图能力按 Kie 当前支持）
6. Gemini Omni Video（时长按 Kie 当前模型支持）
7. Seedance 2.0（最长 15s；支持 0/1/2/3-9 图或视频/音频参考）
8. Seedance 2.0 Fast（最长 15s；同 Seedance 路由）
9. Seedance 2.0 Mini（最长 15s；同 Seedance 路由）
直接回车：使用默认 4
```

```text
请选择视频模型，回复编号即可：
1. Grok Imagine（最高 6s）
2. Grok Imagine Video 1.5 Preview（最高 8s）
3. Veo3.1 Lite（最高 8s）
4. Veo3.1 Fast（最高 8s）
5. Veo3.1 Quality（最高 8s）
6. Gemini Omni Video（最高 4s）
7. Seedance 2.0（最高 15s）
8. Seedance 2.0 Fast（最高 15s）
9. Seedance 2.0 Mini（最高 15s）
直接回车：使用默认 4
```

Ignore any older duration examples above that conflict with the current correct model list.

After the video model is selected, ask duration using the selected model's supported list:

```text
Grok Imagine：4s / 6s / 8s / 10s / 15s / 20s / 25s / 30s
Grok Imagine Video 1.5 Preview：4s / 6s / 8s / 10s / 15s
Veo3.1 Lite/Fast/Quality：固定约 8s
Gemini Omni Video：除非新增确认上限，否则展示 Kie 已知时长选项
Seedance 2.0/Fast/Mini：4s / 6s / 8s / 10s / 15s
直接回车：默认 6s；Veo 固定默认 8s
```

Legacy example retained only for context:

```text
请选择视频时长，回复编号即可：
1. 4s
2. 6s
3. 8s
直接回车：使用默认 6s
```

## Authentication

Kie API key lookup order:

1. `--api-key`
2. `H_KIE_API_KEY`
3. `KIE_API_KEY`
4. `<home>/.codex/secrets/h_kie_api_key.txt`
5. Plugin-local `.h_api_key`

Do not print API keys. If multiple key sources differ, print only source names plus safe fingerprints, then use the highest-priority source.

## Reverse Text Models

- Default: `gpt-5-5`
- Fallback: `gpt-5-4`
- Gemini options:
  - `gemini-3.1-pro`
  - `gemini-3-pro`
  - `gemini-3.5-flash`
  - `gemini-3-flash`

Request formats:

- `gpt-5-5` and `gpt-5-4` use Kie `/codex/v1/responses` with `input_text` plus `input_image`.
- Gemini models use Kie `/{model}/v1/chat/completions` with OpenAI-style text plus `image_url` content.

## Image Model Choices

- `1` = GPT Image-2
- `2` = Nano Banana
- `3` = Nano Banana Pro
- `4` = Nano Banana 2
- `5` = Nano Banana 2 Lite
- `6` = Seedream 5.0 Lite

Image payload rules:

- The user chooses a model family, not a raw Kie endpoint.
- The script selects the Kie endpoint from whether an input image is present.
- If an image is present, use the image/edit endpoint for that model family.
- If no image is present, use the text-to-image endpoint for that model family when one exists.
- Only pass source image fields to image/edit endpoints.
- User-facing image resolution choices must be `1=1K`, `2=2K`, `3=4K`.
- GPT Image-2 uses `aspect_ratio`.
- Nano Banana family uses `output_format=png` and the model's documented image field.
- Seedream 5.0 Lite uses `aspect_ratio`, `quality`, and `nsfw_checker`.
- Pass resolution only to models whose docs accept resolution.

## Video Model Choices

- `1` = Grok Imagine
- `2` = Grok Imagine Video 1.5 Preview
- `3` = Veo3.1 Lite
- `4` = Veo3.1 Fast
- `5` = Veo3.1 Quality
- `6` = Gemini Omni Video
- `7` = Seedance 2.0
- `8` = Seedance 2.0 Fast
- `9` = Seedance 2.0 Mini

Video payload rules:

- The user chooses a video model family, not a raw Kie `text-to-video` / `image-to-video` endpoint.
- The script selects the Kie endpoint from whether an input image is present.
- User-facing video model choices must include these confirmed duration rules: Veo3.1 Lite/Fast/Quality fixed about 8s with no manual duration parameter; Grok Imagine max 30s; Grok Imagine Video 1.5 Preview max 15s; Seedance 2.0/Fast/Mini max 15s. If a future Kie model has only example durations, do not treat examples as maximums.
- User-facing duration choices must be filtered by confirmed maximum supported duration. For Veo3.1, show only fixed 8s.
- Veo3.1 uses the dedicated Kie Veo endpoint. It supports 0 images as `TEXT_2_VIDEO`, 1-2 images as `FIRST_AND_LAST_FRAMES_2_VIDEO`, and exactly 3 images as `REFERENCE_2_VIDEO`; more than 3 images must fail before submission. Do not send video or audio references to Veo.
- Grok Imagine uses `grok-imagine/image-to-video` when one processed image is present and `grok-imagine/text-to-video` when no image is present. More than 1 image must fail before submission. Do not send video or audio references to Grok.
- Grok 1.5 Preview uses `image_urls` only when 1 image is present, plus `aspect_ratio`, `resolution`, and numeric `duration`. More than 1 image or any video/audio reference must fail before submission.
- Gemini Omni Video uses `image_urls` only when an image is present and always uses `duration`; do not pass unsupported resolution/aspect fields.
- Seedance 2.0 uses no media for text-to-video, `first_frame_url` for 1 image, `first_frame_url` plus `last_frame_url` for 2 images, and `reference_image_urls` / `reference_video_urls` / `reference_audio_urls` for 3-9 images or any video/audio references. These Seedance scenarios are mutually exclusive.
- Grok Imagine Video Upscale and Grok Imagine Video Extend are post-processing operations that require an existing Kie task/video; do not list them as primary first-generation model choices unless the workflow explicitly asks for an upscale/extend stage.

## Common Options

Aspect ratio:

- `1` = `9:16`
- `2` = `16:9`

Prompt variables:

- `{pid}`
- `{product_id}`

Concurrency:

- `--workers 0` means one worker per image/video under the whole input root, capped at 64.
- Never process subfolders one at a time unless the user explicitly requests staged folder-by-folder processing.

## Commands

Stage 1:

```bash
python scripts/h_run.py process-images "/path/to/root" \
  --image-model 1 \
  --aspect-ratio 2 \
  --reverse-model gpt-5-5 \
  --image-reverse-meta-prompt "将每张产品图片反推为详细的 Kie 图片生成提示词。PID：{pid}"
```

Stage 2:

```bash
python scripts/h_run.py generate-videos "/path/to/root" \
  --video-model 5 \
  --aspect-ratio 2 \
  --reverse-model gpt-5-5 \
  --video-reverse-meta-prompt "将这张处理后的产品图片反推为 Kie 视频生成提示词。PID：{pid}"
```

Windows PowerShell example:

```powershell
python .\scripts\h_run.py process-images "C:\path\to\root" `
  --image-model 1 `
  --aspect-ratio 2 `
  --reverse-model gpt-5-5 `
  --image-reverse-meta-prompt "将每张产品图片反推为详细的 Kie 图片生成提示词。PID：{pid}"
```

Cross-platform plugin rules:

- Python code must use `pathlib.Path`, not hardcoded path separators.
- Desktop path must be computed as `%USERPROFILE%\Desktop` on Windows and `~/Desktop` on macOS.
- Do not depend on Windows-only shell syntax in the plugin logic.
- Keep command examples for both POSIX shells and Windows PowerShell.

## Failure Memory

The previous failure was caused by combining three mistakes:

1. Reverse prompting was not consistently using the actual source image through the intended provider.
2. Batch submission was effectively too serialized for whole-folder work.
3. Kie result parsing could mistake an original/source URL for the generated output URL.

The fixed behavior is:

- Kie-only reverse prompt and generation.
- Whole-root concurrent submission.
- Model-specific request formats.
- Immediate reverse prompt caching.
- Strict generated URL validation.
- Desktop/output-root result format with separate `文本`, `图像`, and `视频` folders.
