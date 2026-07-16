# Install H

## Supported Delivery

A GitHub repository URL pasted into a Codex conversation is not an install command. Use one of the platform-specific portable ZIP packages from the GitHub release:

- `H-Codex-Plugin-Windows-x64.zip`
- `H-Codex-Plugin-macOS-Intel.zip`
- `H-Codex-Plugin-macOS-Apple-Silicon.zip`

Each package includes compiled H launch and core executables with the Python runtime and `requests` embedded. The target computer does not need Python, pip, Homebrew, Git, or the Codex CLI.

## Install From The Extracted Folder

1. Fully extract the ZIP. Do not run files from the archive preview.
2. Windows: run `Install-H-Windows.cmd`.
3. macOS: run `Install-H.command`. If Gatekeeper blocks it, right-click the file and choose Open.
4. The installer copies H to `~/.agents/plugins/plugins/h`, safely merges the personal marketplace, and runs an offline startup check.
5. Fully quit and reopen Codex, then start a new task and invoke H.

You can also give the entire extracted folder to Codex and ask it to run the matching installer file. Do not give Codex only the GitHub repository URL.

## Kie Key

The portable package never contains a Kie key. Configure one source on the target computer:

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

H validates the key before submitting any generation task. Keys are not stored in the plugin repository or portable ZIP.

## Source Development

The source checkout retains `scripts/h_run.cmd` and `scripts/h_run.sh` as a development fallback. They may create a user-level Python environment, but end users should use the portable ZIP packages instead.
