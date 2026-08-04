#!/usr/bin/env python3
"""Build the cross-platform, checksum-pinned AdsPower runtime archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "scripts" / "adspower_runtime"
DEFAULT_OUTPUT = ROOT / "assets" / "adspower-runtime.zip"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_bundle(source: Path, output: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    required = [
        source / "src" / "cli.mjs",
        source / "config.adspower.tiktok.example.json",
        source / "package-lock.json",
        source / "node_modules" / "playwright" / "package.json",
        source / "node_modules" / "playwright-core" / "package.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("AdsPower bundle source is incomplete: " + ", ".join(missing))
    files = sorted(path for path in source.rglob("*") if path.is_file() and not path.is_symlink())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in files:
                relative = path.relative_to(source).as_posix()
                if "\\" in relative or relative.startswith("/") or "../" in relative:
                    raise RuntimeError(f"Unsafe AdsPower bundle path: {relative}")
                info = zipfile.ZipInfo(relative, FIXED_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "archive": str(output),
        "sha256": sha256_file(output),
        "size": output.stat().st_size,
        "files": len(files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    print(json.dumps(build_bundle(Path(args.source), Path(args.output)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
