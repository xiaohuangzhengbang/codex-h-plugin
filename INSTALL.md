# Install H

Use this Git URL in Codex plugin install:

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

The repository root is the plugin root and contains `.codex-plugin/plugin.json`.

After installing, run first-use doctor:

```bash
python scripts/h_run.py --doctor
```

If doctor reports `"ready": true`, the plugin is ready.

## Requirements

- Codex
- Python 3.10+
- Python `venv`
- Network access for first dependency install
- Kie API key

## Kie Key

Recommended:

```text
<home>/.codex/secrets/h_kie_api_key.txt
```

macOS:

```bash
mkdir -p ~/.codex/secrets
printf '%s' 'YOUR_KIE_KEY' > ~/.codex/secrets/h_kie_api_key.txt
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\secrets" | Out-Null
Set-Content -NoNewline "$env:USERPROFILE\.codex\secrets\h_kie_api_key.txt" "YOUR_KIE_KEY"
```
