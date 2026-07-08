# H Codex Plugin

Portable pure-Kie Codex plugin for batch and single image/video workflows.

This repository is a Codex plugin root. It contains:

```text
.codex-plugin/plugin.json
skills/
scripts/
assets/
requirements.txt
```

## Install From Git URL

In Codex, install a plugin from this Git URL:

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

After install, enable plugin `H`.

## First Use

On first use, H should run its bootstrap check:

```bash
python scripts/h_run.py --doctor
```

The doctor command prepares:

- plugin-local `.h_venv`
- `requests>=2.32,<3`
- Desktop output availability
- Kie key source detection

Successful doctor output contains:

```json
{
  "ready": true
}
```

## Kie Key

Do not commit API keys.

Recommended key file:

```text
<home>/.codex/secrets/h_kie_api_key.txt
```

macOS example:

```bash
mkdir -p ~/.codex/secrets
printf '%s' 'YOUR_KIE_KEY' > ~/.codex/secrets/h_kie_api_key.txt
```

Windows PowerShell example:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\secrets" | Out-Null
Set-Content -NoNewline "$env:USERPROFILE\.codex\secrets\h_kie_api_key.txt" "YOUR_KIE_KEY"
```

## Modes

H has two modes:

```text
1. Batch processing
2. Single processing
```

Batch mode processes all eligible files under a folder concurrently.

Single mode calls one selected Kie model once with one prompt and supplied media.

## Output

By default, H writes to:

```text
<home>/Desktop/H_results_<input-folder-name>/
```

The runtime script may create localized subfolders for text, images, and videos.

## Run Commands

Use the portable launcher:

```bash
python scripts/h_run.py ...
```

Do not run `scripts/kie_video_batch.py` directly unless debugging.

## Safety

Ignored by git:

```text
.h_api_key
.h_ready.json
.h_venv/
__pycache__/
*.pyc
```
