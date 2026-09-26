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
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
EXE = "ownrender.exe" if IS_WIN else "ownrender"
SKIP_BUNDLE = False          # --no-bundle-libs 时跳过"补系统库"


def _fix_encoding():
    """Windows 控制台默认 cp1252/cp936，打印中文会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_encoding()


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
           # 注意：素材不塞进二进制。onefile 不压缩、standalone 又必须整套目录一起拷，
           # 把 background/fonts 再放一份进包里纯属浪费 40MB+，它们本来就与可执行文件同级。
           "--nofollow-import-to=pytest,setuptools,pip,unittest,"
           "tkinter,_tkinter,scipy,matplotlib,IPython,pydoc,doctest,"
           "test,lib2to3,distutils,numpy.f2py",
           # 注：刻意不排除 email/http/urllib —— requests 链路要它们，排了会让 AI 模式在真机上炸
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


def _elf_load_ok(path: Path) -> bool:
    """校验每个 PT_LOAD 的 offset 与 vaddr 是否同余于 align。

    某些链接器产出的 .so 在 strip 后会破坏页对齐，加载时直接报
    「ELF load command address/offset not page-aligned」，因此剥完必须验一遍。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        if head[:4] != b"\x7fELF":
            return True
        is64 = head[4] == 2
        if is64:
            phoff = int.from_bytes(head[0x20:0x28], "little")
            entsz = int.from_bytes(head[0x36:0x38], "little")
            num = int.from_bytes(head[0x38:0x3A], "little")
        else:
            phoff = int.from_bytes(head[0x1C:0x20], "little")
            entsz = int.from_bytes(head[0x2A:0x2C], "little")
            num = int.from_bytes(head[0x2C:0x2E], "little")
        with open(path, "rb") as f:
            f.seek(phoff)
            buf = f.read(entsz * num)
    except (OSError, ValueError):
        return True
    for i in range(num):
        ph = buf[i * entsz:(i + 1) * entsz]
        if len(ph) < entsz or int.from_bytes(ph[0:4], "little") != 1:
            continue                                    # 只看 PT_LOAD
        if is64:
            off = int.from_bytes(ph[8:16], "little")
            vaddr = int.from_bytes(ph[16:24], "little")
            align = int.from_bytes(ph[48:56], "little")
        else:
            off = int.from_bytes(ph[4:8], "little")
            vaddr = int.from_bytes(ph[8:12], "little")
            align = int.from_bytes(ph[28:32], "little")
        if align > 1 and off % align != vaddr % align:
            return False
    return True


def _dlopen_ok(path: Path) -> bool:
    """真让动态加载器加载一次，确认 strip 没把库弄坏。

    _elf_load_ok 只查静态表；这里在子进程里 dlopen，能复现
    「ELF load command address/offset not page-aligned」这类**运行时**错误。
    只把「文件被弄坏」类错误算失败；undefined symbol 之类是该库自身的加载前提，
    不算 strip 的锅（否则会误还原一堆本来就好好的库）。
    """
    n = path.name
    if not (n.endswith((".so", ".dylib")) or ".so." in n):
        return True
    code = "import ctypes,sys;ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_LOCAL)"
    try:
        r = subprocess.run([sys.executable, "-c", code, str(path)],
                           capture_output=True, text=True, timeout=120)
    except Exception:                                    # noqa: BLE001
        return True
    if r.returncode == 0:
        return True
    err = (r.stderr or "").lower()
    fatal = ("page-aligned", "invalid elf", "failed to map segment",
             "wrong elf class", "truncated", "too short",
             "cannot read file data", "cannot open shared object")
    return not any(k in err for k in fatal)


def _strip_tree(dest: Path):
    """剥掉符号表。

    Python 运行时与 numpy(OpenBLAS) 的 .so 默认带完整符号：
    libpython 28MB → 6MB、openblas 26MB → 8MB 这种量级，是体积最大的一块肥肉。
    剥完必须校验（见 _elf_load_ok），坏了就还原 —— 宁可少省几 MB 也不能让包跑不起来。
    """
    args = ["--strip-unneeded"] if not (IS_WIN or IS_MAC) else ["-x"]
    exe = shutil.which("strip") or (shutil.which("strip.exe")
                                    if IS_WIN else None)
    if not exe:
        print("== 未找到 strip，跳过剥符号")
        return
    magics = (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
              b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce")
    n = saved = bad = 0
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            with open(p, "rb") as f:
                if f.read(4) not in magics:
                    continue
            before_bytes = p.read_bytes()
        except OSError:
            continue
        before = len(before_bytes)
        try:
            r = subprocess.run([exe] + args + [str(p)],
                               capture_output=True, timeout=300)
        except Exception:                                    # noqa: BLE001
            continue
        if r.returncode != 0:
            continue
        if not _elf_load_ok(p) or not _dlopen_ok(p):
            p.write_bytes(before_bytes)                      # 还原
            bad += 1
            why = "段对齐" if not _elf_load_ok(p) else "实际加载"
            print(f"   ! 还原（strip 破坏{why}）: {p.name}")
            continue
        n += 1
        saved += max(0, before - p.stat().st_size)
    print(f"== 剥符号 {n} 个文件，省下 {saved / 1048576:.1f} MB"
          f"（还原 {bad} 个）")


def _find_system_lib(soname: str):
    """在系统里找一个 soname 对应的真实文件（优先 ldconfig 缓存）。"""
    try:
        r = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=60)
        for line in r.stdout.splitlines():
            if soname in line and "=>" in line:
                p = line.split("=>", 1)[1].strip()
                if os.path.isfile(p):
                    return p
    except Exception:
        pass
    for d in ("/lib", "/usr/lib", "/lib64", "/usr/lib64", "/lib32", "/usr/lib32",
              "/usr/local/lib", "/opt/lib"):
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            if soname in files:
                return os.path.join(root, soname)
    return None


# 必须由目标机器提供的库：glibc 家族（跟宿主 ld.so 强绑定）与
# 显卡/窗口/驱动栈（跟宿主驱动强绑定）。这些打进包里不仅没用，还可能炸。
SYSTEM_ONLY = (
    "ld-linux", "ld-2.", "ld.so", "libc.so", "libc-2.", "libm.so", "libm-2.",
    "libdl.so", "libpthread", "librt.so", "libresolv", "libutil.so",
    "libnsl.so", "libcrypt.so", "libanl.so", "libmvec.so", "libthread_db.so",
    "libGL", "libEGL", "libGLX", "libOpenGL", "libGLdispatch", "libGLESv",
    "libdrm.so", "libgbm.so", "libvulkan", "libnvidia", "libcuda.so",
    "libX11", "libxcb", "libwayland", "libxkbcommon", "libICE.so", "libSM.so",
)

_PT_LOAD, _PT_DYNAMIC = 1, 2


def _is_system_only(soname: str) -> bool:
    return any(soname.startswith(p) for p in SYSTEM_ONLY)


def _elf_needed(path):
    """读 ELF 的 DT_NEEDED（纯 Python 解析动态段，不依赖 binutils）。

    为什么不用 ldd：ldd 是在"当前机器"上解析，构建容器恰好装了某个库时，
    就永远看不出它没被打进包——libblas.so.3 就是这么漏过去的。
    DT_NEEDED 是文件里的静态信息，与构建机装了什么无关，才靠得住。
    """
    if IS_WIN:
        return []
    try:
        data = path.read_bytes()
    except Exception:
        return []
    if len(data) < 64 or data[:4] != b"\x7fELF":
        return []
    is64 = data[4] == 2
    end = "<" if data[5] == 1 else ">"
    try:
        if is64:
            e_phoff, = struct.unpack_from(end + "Q", data, 0x20)
            e_phentsize, e_phnum = struct.unpack_from(end + "HH", data, 0x36)
        else:
            e_phoff, = struct.unpack_from(end + "I", data, 0x1c)
            e_phentsize, e_phnum = struct.unpack_from(end + "HH", data, 0x2a)
        loads, dyn = [], None
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            if off + e_phentsize > len(data):
                break
            p_type, = struct.unpack_from(end + "I", data, off)
            if is64:
                p_offset, p_vaddr, _pp, p_filesz = struct.unpack_from(end + "QQQQ", data, off + 8)
            else:
                _ptype, p_offset, p_vaddr, _pp, p_filesz = struct.unpack_from(
                    end + "IIIII", data, off)
            if p_type == _PT_LOAD:
                loads.append((p_vaddr, p_filesz, p_offset))
            elif p_type == _PT_DYNAMIC:
                dyn = (p_offset, p_filesz)
        if not dyn:
            return []

        def v2o(addr):
            for vaddr, filesz, offset in loads:
                if vaddr <= addr < vaddr + filesz:
                    return offset + (addr - vaddr)
            return None

        entsz = 16 if is64 else 8
        fmt = end + ("QQ" if is64 else "II")
        strtab = strsz = None
        idxs = []
        o, sz = dyn
        for pos in range(o, min(o + sz, len(data) - entsz + 1), entsz):
            tag, val = struct.unpack_from(fmt, data, pos)
            if tag == 0:
                break
            if tag == 5:
                strtab = val
            elif tag == 10:
                strsz = val
            elif tag == 1:
                idxs.append(val)
        if strtab is None or strsz is None or not idxs:
            return []
        base = v2o(strtab)
        if base is None:
            return []
        blob = data[base:base + strsz]
        out = []
        for i in idxs:
            e = blob.find(b"\x00", i)
            out.append(blob[i:e if e >= 0 else len(blob)].decode("utf-8", "replace"))
        return out
    except Exception as exc:
        print(f"   ! 读 {path.name} 的 DT_NEEDED 失败：{exc}")
        return []


def _bundle_system_libs(dest: Path) -> None:
    """把包内 ELF 需要、但包里没有的共享库补进便携目录。

    为什么需要：某些发行版的 python3-numpy 链接系统 BLAS（libblas.so.3），
    它属于"系统库"而非 Python 扩展，Nuitka standalone 不会带；
    构建容器恰好装了它 → 冒烟测试照样通过，用户机器上却 ImportError。
    做法：按 DT_NEEDED 找出"包内没有、且不属于 glibc/显卡家族"的 soname，
    从系统复制到包根（Nuitka 的 RPATH 是 $ORIGIN 系，包根即可命中），
    最多 4 轮直到依赖闭合，最后复查一次。
    """
    if IS_WIN:
        return

    def elf_files():
        for p in dest.rglob("*"):
            if p.is_file() and (p.name == EXE or ".so" in p.name):
                yield p

    def missing_now():
        """包内 ELF 需要、包里却没有、且不该由系统提供的 soname。"""
        present = {q.name for q in dest.rglob("*") if q.is_file()}
        out = {}
        for p in elf_files():
            for so in _elf_needed(p):
                if so in present or _is_system_only(so):
                    continue
                out.setdefault(so, p)
        return out

    added = {}
    for rnd in range(4):
        missing = missing_now()
        if not missing:
            break
        print(f"== 系统库补全 第{rnd + 1}轮：缺 {len(missing)} 个 {sorted(missing)[:10]}")
        gone = True
        for soname, holder in missing.items():
            src = _find_system_lib(soname)
            if not src:
                print(f"   ! 系统里也找不到 {soname}（{holder.name} 需要）")
                gone = False
                continue
            dst = dest / soname
            if not dst.exists():
                shutil.copy2(src, dst)
                os.chmod(dst, 0o755)
                added[soname] = src
        if gone:
            break

    left = missing_now()
    if added:
        tot = sum((dest / k).stat().st_size for k in added) / 1048576
        print(f"== 已补入 {len(added)} 个系统库（{tot:.1f} MB）：{sorted(added)}")
    if left:
        print(f"   ! 仍有未解析依赖：{sorted(left)} —— 该包在干净系统上可能跑不起来")
    else:
        print("== 自包含检查通过：包内 ELF 无未解析依赖（glibc 家族除外）")


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

    # 3) 剥符号（只对刚组装好的副本动手，不影响 dist 里的原产物）
    _strip_tree(dest)

    # 3.5) 补全"系统库"依赖，保证包在任何干净机器上都自包含
    if not SKIP_BUNDLE:
        _bundle_system_libs(dest)

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
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=9) as z:
            for p in dest.rglob("*"):
                z.write(p, p.relative_to(dest.parent))
        return zpath
    tpath = Path(str(dest) + ".tar.gz")
    with tarfile.open(tpath, "w:gz", compresslevel=9) as t:
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
    ap.add_argument("--no-bundle-libs", action="store_true",
                    help="跳过把系统共享库补进便携目录（默认会补）")
    a = ap.parse_args()

    global SKIP_BUNDLE
    SKIP_BUNDLE = a.no_bundle_libs

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