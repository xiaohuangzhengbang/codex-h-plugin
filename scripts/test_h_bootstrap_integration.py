import json
import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
LAUNCHER = SCRIPT_DIR / "h_run.py"


def parse_last_json(output: str):
    lines = output.strip().splitlines()
    for start in range(len(lines)):
        try:
            value = json.loads("\n".join(lines[start:]))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"No JSON object in launcher output:\n{output[-2000:]}")


def run_start(codex_home: Path):
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "start", "--offline"],
        cwd=str(SCRIPT_DIR.parent),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=900,
    )
    assert result.returncode == 0, result.stdout
    return parse_last_json(result.stdout)


def main():
    configured_home = os.environ.get("CODEX_HOME") if os.environ.get("H_CI_BOOTSTRAP_TEST") == "1" else ""
    context = nullcontext(Path(configured_home)) if configured_home else tempfile.TemporaryDirectory(prefix="h-bootstrap-test-")
    with context as value:
        codex_home = Path(value)
        first = run_start(codex_home)
        assert first["ready"] is True
        assert first["state"] == "mode"
        assert first["bootstrap"]["environment_created"] is True
        assert first["bootstrap"]["dependencies_installed"] is True
        assert set(first["bootstrap"]["missing_before"]) == {"requests", "openpyxl"}

        second = run_start(codex_home)
        assert second["ready"] is True
        assert second["bootstrap"]["environment_created"] is False
        assert second["bootstrap"]["dependencies_installed"] is False
        assert second["bootstrap"]["marker_was_current"] is True
        assert second["bootstrap"]["missing_before"] == []

    print("PASS first-use install and second-use reuse integration test")


if __name__ == "__main__":
    main()
