# H

H is a portable pure-Kie Codex plugin for product image and video workflows.

It has two user-facing modes:

```text
1. 批处理
2. 单处理
```

- `批处理`: process every eligible item under one folder/root concurrently.
- `单处理`: call one selected Kie model once with one prompt and supplied media.

## Portable Runtime

Always run commands through:

```bash
python scripts/h_run.py ...
```

The launcher uses only the Python standard library, creates a plugin-local `.h_venv`, installs `requirements.txt` quietly, and then runs the real workflow script. This avoids repeated failures on new Windows/macOS machines where `requests` is not installed.

First load on a new computer should run:

```bash
python scripts/h_run.py --doctor
```

Doctor checks and prepares:

- Python + `venv`
- plugin-local `.h_venv`
- `requests>=2.32,<3`
- main script presence
- Desktop output availability
- Kie API key source

Successful doctor writes `.h_ready.json`; future runs skip the visible bootstrap unless the environment is missing.

## Output

By default, H writes to the user's Desktop:

```text
Desktop/H返回结果_<input-folder-name>/
  文本/
  图像/
  视频/
```

## Batch Image Stage

```bash
python scripts/h_run.py process-images "/path/to/root" \
  --image-model 1 \
  --image-resolution 1 \
  --aspect-ratio 2 \
  --reverse-model 1 \
  --image-reverse-meta-prompt "将每张产品图片反推为详细的 Kie 图片生成提示词。PID：{pid}"
```

`--resolution` is kept as a compatibility alias for `--image-resolution`.

## Batch Video Stage

```bash
python scripts/h_run.py generate-videos "/path/to/root" \
  --video-model 5 \
  --duration 8 \
  --aspect-ratio 2 \
  --reverse-model 1 \
  --video-reverse-meta-prompt "将这张处理后的产品图片反推为 Kie 视频生成提示词。PID：{pid}"
```

## Secrets

Kie API key lookup order:

1. `--api-key`
2. `H_KIE_API_KEY`
3. `KIE_API_KEY`
4. `<home>/.codex/secrets/h_kie_api_key.txt`
5. Plugin-local `.h_api_key`

Do not publish plugin-local key files publicly.
