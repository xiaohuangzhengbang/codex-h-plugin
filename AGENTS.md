# H Repository Contract For Codex

When a user gives this repository URL and asks to install H, treat the repository as a Codex plugin marketplace. Do not redirect the user to a ZIP package, do not install it as a standalone skill, and do not stop after cloning or inspecting the repository.

## Required Installation

1. Locate a working Codex CLI. Prefer `codex` from `PATH`. In Codex Desktop on macOS, also check `/Applications/Codex.app/Contents/Resources/codex` and `~/Applications/Codex.app/Contents/Resources/codex`.
   On Windows, if the `WindowsApps` command alias returns `Access is denied`, locate the newest `C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe`, copy it to `%TEMP%\codex-h-installer.exe`, and invoke that copy for the commands below.
2. Add or refresh this Git marketplace:

   ```text
   codex plugin marketplace add https://github.com/xiaohuangzhengbang/codex-h-plugin.git --ref main
   ```

   If it already exists, use:

   ```text
   codex plugin marketplace upgrade codex-h-plugin
   ```

3. Confirm H is installed:

   ```text
   codex plugin add h@codex-h-plugin
   ```

4. Verify with `codex plugin list --json`. The installed plugin ID must be `h@codex-h-plugin`.
5. Do not manually install Python, Node, npm, pip, `requests`, Playwright, XLSX, Homebrew, or a Release ZIP. On first invocation, `scripts/h_run.cmd` or `scripts/h_run.sh` scans all required runtimes and automatically obtains verified Windows x64, Intel Mac, or Apple Silicon components when necessary. Runtime setup is capability-scoped: PID does not prepare AdsPower, generation does not prepare AdsPower, and only publishing prepares Node. Playwright is stored as the checksum-pinned `assets/adspower-runtime.zip` instead of tracked `node_modules`, then extracted to a short user cache path.
   When AdsPower source or dependencies change, run `npm ci --ignore-scripts --omit=dev` in `scripts/adspower_runtime`, rebuild with `python scripts/build_adspower_bundle.py`, and update `ADSPOWER_RUNTIME_SHA256` from the script output. Never commit `node_modules`.
6. Tell the user to fully quit and reopen Codex and start a new task after installation.

H has exactly three top-level entries: PID, generation, and publishing. Generation alone contains batch and single processing. Route a numeric product PID through FastMoss; route images through generation; when PID and image are both present, the image is the visual source and PID supplies title context plus exact product attachment. Successful video generation must offer direct publishing of the current `output_root`; do not make the user locate generated videos again.

Every PID-attached publish plan must preserve an exact one-to-one video/PID mapping and reject the whole plan if any PID is missing or nonnumeric. Schedule intervals must be positive multiples of 30 minutes. AdsPower preview never clicks the final button, and formal publishing requires the user's explicit `FABU` confirmation.

The canonical marketplace file is `.agents/plugins/marketplace.json`. The canonical plugin manifest is `.codex-plugin/plugin.json`.
