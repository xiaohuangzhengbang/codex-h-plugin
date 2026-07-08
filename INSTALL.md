# Install H In Codex

Copy the entire `h` folder into your personal Codex plugin location, then install it from the Codex plugin UI or personal marketplace.

## Runtime

No manual `pip install` step is required.

First load/bootstrap:

```bash
python scripts/h_run.py --doctor
```

Use:

```bash
python scripts/h_run.py ...
```

The launcher creates a plugin-local `.h_venv`, installs the dependencies from `requirements.txt` quietly, and writes `.h_ready.json` after a successful doctor run. This works on Windows, macOS Intel, and macOS Apple Silicon as long as Codex has a usable Python interpreter with `venv`.

## API Key

Kie key lookup:

1. `--api-key`
2. `H_KIE_API_KEY`
3. `KIE_API_KEY`
4. `<home>/.codex/secrets/h_kie_api_key.txt`
5. Plugin-local `.h_api_key`

Recommended portable secret file:

```text
<home>/.codex/secrets/h_kie_api_key.txt
```

Or set an environment variable:

```powershell
$env:KIE_API_KEY="YOUR_KIE_API_KEY"
```

```bash
export KIE_API_KEY="YOUR_KIE_API_KEY"
```

## Modes

H should ask only:

```text
请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
```

Then it asks the parameters for that mode.
