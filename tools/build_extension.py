"""Build and package PerfectPixel as an official .aseprite-extension.

This script:
1. Copies compiled `dist/perfect_pixel_cli.exe` into `aseprite_extension/bin/`.
2. Packages `aseprite_extension/` into a standard `.aseprite-extension` zip archive.
3. Outputs the ready-to-install extension in `out/`.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = ROOT / "aseprite_extension"
BIN_DIR = EXT_DIR / "bin"
DIST_EXE = ROOT / "dist" / "perfect_pixel_cli.exe"
OUT_DIR = ROOT / "out"


def main() -> int:
    print("=== Building PerfectPixel Aseprite Extension ===")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    DIST_DIR = ROOT / "dist" / "perfect_pixel_cli"
    DIST_EXE = ROOT / "dist" / "perfect_pixel_cli.exe"

    # 清空旧 bin 目录
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 优先复制高性能免解压的 onedir 执行树，秒级响应
    if DIST_DIR.is_dir():
        print(f"Copying fast onedir executable tree: {DIST_DIR} -> {BIN_DIR}")
        for item in DIST_DIR.iterdir():
            dest = BIN_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    elif DIST_EXE.is_file():
        target_exe = BIN_DIR / "perfect_pixel_cli.exe"
        print(f"Copying standalone exe: {DIST_EXE} -> {target_exe}")
        shutil.copy2(DIST_EXE, target_exe)
    else:
        print(
            "Warning: dist executable not found! Bundling Python scripts instead..."
        )
        shutil.copy2(
            ROOT / "perfect_pixel_cli.py", BIN_DIR / "perfect_pixel_cli.py"
        )
        shutil.copy2(
            ROOT / "perfect_pixel_core.py", BIN_DIR / "perfect_pixel_core.py"
        )

    # 2. 打包生成 .aseprite-extension 扩展包
    extension_pkg = OUT_DIR / "perfect-pixel-v1.0.0.aseprite-extension"
    print(f"Creating extension package: {extension_pkg}")

    with zipfile.ZipFile(
        extension_pkg, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for file_path in EXT_DIR.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(EXT_DIR)
                # 排除临时文件
                if rel_path.name.startswith((".", "~")):
                    continue
                posix_rel = rel_path.as_posix()
                print(f"  + Packing: {posix_rel}")
                archive.write(file_path, arcname=posix_rel)

    size_mb = extension_pkg.stat().st_size / (1024 * 1024)
    print(f"\n[Success] Aseprite Extension built successfully!")
    print(f"Package Path: {extension_pkg}")
    print(f"Package Size: {size_mb:.2f} MB")
    print("\nHow to install in Aseprite:")
    print("  1. Double click 'perfect-pixel-v1.0.0.aseprite-extension' directly.")
    print(
        "  2. Or inside Aseprite: Edit -> Preferences -> Extensions -> Add Extension."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
