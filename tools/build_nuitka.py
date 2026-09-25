#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nuitka 打包驱动（CI / 本地通用）

用法：
    python tools/build_nuitka.py --onefile --out dist
    python tools/build_nuitka.py --no-onefile --out dist      # standalone 目录
    python tools/build_nuitka.py --assemble-only --out dist --name OwnRender-linux-x86_64

产物：
    dist/OwnRender-<platform>-<arch>/            便携目录
        ├── ownrender(.exe)      可执行文件
        ├── background/          材质底图（可自行替换）
        ├── fonts/               字体（可自行替换）
        ├── docs/  README.md  LICENSE  CREDITS.md
        └── RUN.txt              快速上手
    dist/OwnRender-<platform>-<arch>.zip|.tar.gz 压缩包（--archive）
说明：
    素材不打进二进制包内，而是与可执行文件同级放置 —— 这样运行行为与
    直接跑源码脚本完全一致，用户也能随时替换字体/底图。
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
EXE = "ownrender.exe" if IS_WIN else "ownrender"


def arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
            "arm64": "aarch64"}.get(m, m)


def platform_name() -> str:
    if IS_WIN:
        return "windows"
    if IS_MAC:
        return "macos"
    return "linux"


def nuitka_version() -> tuple:
    try:
        out = subprocess.run([sys.executable, "-m", "nuitka", "--version"],
                             capture_output=True, text=True).stdout
        nums = [int(x) for x in out.strip().split(".")[:2]]
        return tuple(nums)
    except Exception:
        return (0, 0)


def build(out: Path, onefile: bool):
    out.mkdir(parents=True, exist_ok=True)
    ver = (ROOT / "config.py").read_text(encoding="utf-8")
    version = ver.split('VERSION = "')[1].split('"')[0]

    cmd = [sys.executable, "-m", "nuitka",
           "--onefile" if onefile else "--standalone",
           "--assume-yes-for-downloads",
           "--enable-plugin=numpy",
           # 本项目的三个子框架必须显式包含
           "--include-package=frame_light",
           "--include-package=frame_render",
           "--include-package=frame_interact",
           # 网络与证书
           "--include-package=certifi",
           "--include-package-data=certifi",
           # 兜底素材（可执行文件旁边没有时用它们）
           "--include-data-dir=background=background",
           "--include-data-dir=fonts=fonts",
           "--nofollow-import-to=pytest,setuptools,pip,unittest",
           f"--output-dir={out}",
           f"--output-filename={EXE}",
           "--company-name=OwnRender",
           "--product-name=OwnRender",
           f"--file-version={version}",
           f"--product-version={version}",
           "--copyright=GNU AGPL-3.0 (C) 2025 yingo-server and contributors",
           ]
    if IS_WIN and nuitka_version() >= (2, 3):
        cmd.append("--windows-console-mode=force")
    cmd.append("main.py")

    print("== Nuitka 命令 ==")
    print(" ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        sys.exit(f"Nuitka 构建失败，返回码 {r.returncode}")


def assemble(out: Path, name: str, onefile: bool) -> Path:
    """把可执行文件与素材/文档组装成便携目录。"""
    dest = out / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # 1) 可执行文件
    exe = out / EXE
    if not exe.exists():
        # standalone 模式产物在 main.dist/ 里
        cand = list(out.glob("main.dist/*"))
        if not cand:
            sys.exit(f"找不到构建产物：{exe}")
        for p in cand:
            dst = dest / p.name
            shutil.copytree(p, dst) if p.is_dir() else shutil.copy2(p, dst)
    else:
        shutil.copy2(exe, dest / EXE)
    if not IS_WIN:
        os.chmod(dest / EXE, 0o755)

    # 2) 素材与文档
    for d in ("background", "fonts", "docs", "tools"):
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, dest / d)
    for f in ("README.md", "README.en.md", "LICENSE", "CREDITS.md"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dest / f)

    # 3) 快速上手
    (dest / "RUN.txt").write_text(
        f"""OwnRender {platform_name()}-{arch()}
================================================
可执行文件: {EXE}

【图形界面（TUI）】
    ./{EXE}                      # Windows: {EXE}

【参数模式（脚本用法完全一致）】
    ./{EXE} --offline-bg 微水泥 -y
    ./{EXE} --offline-bg 微水泥 --time "2025-06-21T09:00:00+08:00" \\
            --lat 39.9042 --lon 116.4074 --weather clear -y
    ./{EXE} --help

【素材】
    background/  材质底图，换成自己的图片即可（png/jpg/webp/bmp）
    fonts/       字体（ttf/otf/ttc/otc/woff/woff2）
    也可用环境变量指定便携根目录:  OWNRENDER_HOME=/path/to/dir

【定位】
    本机 GPS 需要系统支持（见 docs/二进制包.md 的"定位适配"一节）
    不装也能用:  --lat/--lon 直接给坐标，或 --set-location 写入缓存

完整文档见 docs/ 目录；许可: GNU AGPL-3.0（LICENSE）
""", encoding="utf-8")
    return dest


def archive(dest: Path) -> Path:
    if IS_WIN:
        zpath = dest.with_suffix(".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in dest.rglob("*"):
                z.write(p, p.relative_to(dest.parent))
        return zpath
    tpath = Path(str(dest) + ".tar.gz")
    with tarfile.open(tpath, "w:gz") as t:
        t.add(dest, arcname=dest.name)
    return tpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true", default=True)
    ap.add_argument("--no-onefile", dest="onefile", action="store_false")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--name")
    ap.add_argument("--assemble-only", action="store_true")
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()

    out = (ROOT / a.out).resolve()
    name = a.name or f"OwnRender-{platform_name()}-{arch()}"

    if not a.assemble_only:
        build(out, a.onefile)
    dest = assemble(out, name, a.onefile)
    print(f"== 便携目录: {dest}")
    if a.archive:
        p = archive(dest)
        print(f"== 压缩包:   {p}  ({p.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()