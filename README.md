# H Codex Plugin

H is a Kie-only Codex plugin with two user-facing modes:

1. Batch processing: recursively process every eligible PID image under one root with whole-root concurrency.
2. Single processing: call one selected Kie text, image, video, upscale, or extend model.

## Install From GitHub

Add this repository as a Codex plugin marketplace:

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

CLI equivalent:

```bash
codex plugin marketplace add https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

Then install or enable `h` from the `codex-h-plugin` marketplace. The repository root already contains both `.agents/plugins/marketplace.json` and `.codex-plugin/plugin.json`.

## First Use

H supports Windows, Intel Mac, and Apple Silicon Mac. Its launcher creates one reusable environment under `<home>/.codex/cache/h`; plugin updates do not reinstall dependencies unless `requirements.txt` changes.

Windows:

```powershell
scripts\h_run.cmd doctor
```

macOS:

```bash
./scripts/h_run.sh doctor
```

Requirements are Python 3.10+, Python `venv`, and network access on the first run. Runtime dependencies are installed automatically.

## Kie Key

API keys are never stored in Git. Configure one source once:

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

The launcher also provides an interactive local setup command:

```bash
./scripts/h_run.sh set-key
```

On Windows, use `scripts\h_run.cmd set-key`.

## Commands

List all models and their constraints without using a Kie key:

```bash
./scripts/h_run.sh catalog
```

Batch images:

```bash
./scripts/h_run.sh process-images "/path/to/root" \
  --image-model 1 --image-resolution 1 --aspect-ratio 2 \
  --reverse-model 1 \
  --image-reverse-meta-prompt "Reverse this product image for Kie. PID: {pid}"
```

Batch videos:

```bash
./scripts/h_run.sh generate-videos "/path/to/root" \
  --video-model 3 --video-resolution 720p --aspect-ratio 2 \
  --reverse-model 1 \
  --video-reverse-meta-prompt "Reverse this processed image into a Kie video prompt. PID: {pid}"
```

Single call:

```bash
./scripts/h_run.sh single --kind image --model 1 --prompt "Product lookbook photo" --media "/path/to/reference.png"
```

Resume an already submitted task without paying for a duplicate submission:

```bash
./scripts/h_run.sh resume "/path/to/task-record.json"
```

## Output

Batch results:

```text
<home>/Desktop/H返回结果_<input-name>/
  文本/
  图像/
  视频/
```

Single results:

```text
<home>/Desktop/H返回结果_单处理/
  文本/
  图像/
  视频/
```

Every submitted item records its `task_id` immediately. Reruns reuse valid prompt caches, resume pending tasks, and only regenerate when the source or request parameters changed. Batch exit code `2` means partial failure; the JSON summary contains exact PID-level causes and next actions.

## Security

- TLS certificate verification remains enabled.
- Downloaded images and videos are checked by file signature before being accepted.
- Keys are logged only as short SHA-256 fingerprints.
- Rotate any key that was ever pasted into a public repository or shared transcript.
