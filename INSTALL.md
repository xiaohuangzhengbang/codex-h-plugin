# Install H

## Codex

Add this Git marketplace URL:

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

Then install `h` from marketplace `codex-h-plugin`.

## One-Time Setup

H needs Python 3.10+ and a Kie API key. It installs `requests` into a reusable user-level virtual environment automatically.

Windows:

```powershell
scripts\h_run.cmd set-key
scripts\h_run.cmd doctor
```

Intel Mac or Apple Silicon Mac:

```bash
./scripts/h_run.sh set-key
./scripts/h_run.sh doctor
```

The key is stored at `<home>/.codex/secrets/h_kie_api_key.txt`. It is not written into the plugin repository.

`doctor` validates the Python runtime, dependency environment, Desktop write access, TLS connection, Kie authentication, and available credits. After it succeeds, invoke H normally from Codex.
