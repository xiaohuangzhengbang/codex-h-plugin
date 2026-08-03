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

The platform launcher first reuses an existing compatible environment. If Python is missing, it downloads the matching Windows x64, Intel Mac, or Apple Silicon runtime from this repository's GitHub Release and verifies its pinned SHA-256 digest. It also scans Node and, when missing, downloads a pinned Node.js LTS archive for the same platform and verifies a built-in SHA-256 digest. Playwright and XLSX packages ship with H. All reusable files are cached under `~/.codex/cache/h`; Homebrew and winget are last-resort fallbacks only.

After Kie video generation, H can create an AdsPower schedule directly from the successful result manifest, run a no-final-click preview, and publish only after the explicit `FABU` confirmation. Standalone publishing from a video folder or XLSX/CSV plan is also available from mode 3.

## Kie Key

The repository and runtime downloads never contain a Kie key. Configure one source on the target computer:

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

H validates the key before submitting generation work.
