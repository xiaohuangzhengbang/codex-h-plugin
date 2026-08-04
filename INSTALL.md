# Install H From GitHub

H is installed from its GitHub marketplace. Portable ZIP extraction is not the normal installation path.

## Give This Repository To Codex

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

Ask Codex to install the H plugin from that URL. The deterministic installation sequence is:

```bash
codex plugin marketplace add https://github.com/xiaohuangzhengbang/codex-h-plugin.git --ref main
codex plugin add h@codex-h-plugin
```

If the marketplace was previously added:

```bash
codex plugin marketplace upgrade codex-h-plugin
codex plugin add h@codex-h-plugin
```

The marketplace marks H as `INSTALLED_BY_DEFAULT`; the explicit `plugin add` command is an idempotent compatibility check.

After installation, fully quit and reopen Codex, then start a new task and invoke H.

## First Run

The installed source plugin does not assume that Python, Node, npm, pip, Homebrew, or Git is available on the target computer.

The platform launcher first reuses an existing compatible environment. If Python is missing, it downloads the matching Windows x64, Intel Mac, or Apple Silicon runtime from this repository's GitHub Release and verifies its pinned SHA-256 digest. It also scans Node and, when missing, downloads a pinned Node.js LTS archive for the same platform and verifies a built-in SHA-256 digest. Playwright ships as one checksum-pinned archive and is expanded into the short `~/.codex/cache/h` path only when publishing starts, so a GitHub checkout never needs deep `node_modules` paths or a target-side `npm install`. XLSX support ships with H. Homebrew and winget are last-resort fallbacks only.

H always exposes three entry points: PID, generation, and publishing. PID lookup retrieves the product cover and title from FastMoss. If the user also supplies an image, that uploaded image remains the visual source while FastMoss contributes title context and the exact product PID. Kie analyzes image and title together, then generated videos can flow directly into AdsPower scheduling.

Publishing uses exact numeric PID attachment and only accepts positive 30-minute schedule intervals. H runs a no-final-click preview and publishes only after the explicit `FABU` confirmation. Standalone publishing from a video folder or XLSX/CSV plan is also available from entry 3.

## Kie Key

The repository and runtime downloads never contain a Kie key. Configure one source on the target computer:

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

H validates the key before submitting generation work.

## FastMoss Key

Configure one source on each target computer:

```text
FASTMOSS_API_KEY
H_FASTMOSS_API_KEY
<home>/.codex/secrets/h_fastmoss_api_key.txt
```

Run `scripts\h_run.cmd set-fastmoss-key` on Windows or `./scripts/h_run.sh set-fastmoss-key` on macOS for a one-time private setup. Never put either API key in GitHub.
