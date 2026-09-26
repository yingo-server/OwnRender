#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收/打包工具链的自测（不需要网络、不需要真包，几秒跑完）

覆盖：
  A. ELF 的 DT_NEEDED 解析（32 位 / 64 位 / 非 ELF）
  B. 系统库归属判定（glibc、显卡家族必须由系统提供；libblas/libz 等应可打包）
  C. 补系统库的「链式递归」（libA→libB→缺 libz）、以及"包内已有一律不误报"
  D. Windows 找主程序（不能把 LICENSE 当 exe —— 曾经的线上事故）
  E. Android 验收的 4 种形态（内嵌归档命中 / 内嵌归档缺失 / p4a-dist 条目命中 / 只给 so.zip）
  F. CLI 文档与代码一致（tools/gen_cli_doc.py --check）

用法：
  python tools/selftest_verify.py            # 全跑，返回码 0=全过，1=有失败
  python tools/selftest_verify.py -v         # 打印细节
"""
import argparse
import gzip
import io
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_nuitka as B            # noqa: E402
import verify_package as V          # noqa: E402

PY = sys.executable
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    mark = "✅" if cond else "❌"
    print("%s %s%s" % (mark, name, ("  — " + detail) if (detail and not cond) else ""))
    return bool(cond)


# ── 造 ELF（可指定位宽与 DT_NEEDED）───────────────────────────────────
def make_elf(needs, bits=32):
    dynstr = b"".join(n.encode() + b"\x00" for n in needs)
    pos, idxs = 0, []
    for n in needs:
        idxs.append(pos)
        pos += len(n) + 1
    if bits == 32:
        entsz, hdr_sz, ph_sz = 8, 52, 32
        dyn_off = 116
        str_off = dyn_off + entsz * (len(needs) + 3)
        total = str_off + len(dynstr)
        hdr = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\x00" * 8
        hdr += struct.pack("<HHIIIIIHHHHHH", 3, 3, 1, 0, hdr_sz, 0, 0,
                           hdr_sz, ph_sz, 2, 40, 0, 0)
        ph0 = struct.pack("<IIIIIIII", 1, 0, 0x1000, 0x1000, total, total, 5, 0x1000)
        ph1 = struct.pack("<IIIIIIII", 2, dyn_off, 0x2000, 0x2000,
                          entsz * (len(needs) + 3), entsz * (len(needs) + 3), 6, 4)
        dyn = struct.pack("<II", 5, 0x1000 + str_off) + struct.pack("<II", 10, len(dynstr))
        for i in idxs:
            dyn += struct.pack("<II", 1, i)
        dyn += struct.pack("<II", 0, 0)
    else:
        entsz, hdr_sz, ph_sz = 16, 64, 56
        dyn_off = 64 + 2 * ph_sz
        str_off = dyn_off + entsz * (len(needs) + 3)
        total = str_off + len(dynstr)
        hdr = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
        hdr += struct.pack("<HHIQQQIHHHHHH", 3, 62, 1, 0, hdr_sz, 0, 0,
                           hdr_sz, ph_sz, 2, 64, 0, 0)
        ph0 = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x1000, 0x1000, total, total, 0x1000)
        n = entsz * (len(needs) + 3)
        ph1 = struct.pack("<IIQQQQQQ", 2, 6, dyn_off, 0x2000, 0x2000, n, n, 8)
        dyn = struct.pack("<QQ", 5, 0x1000 + str_off) + struct.pack("<QQ", 10, len(dynstr))
        for i in idxs:
            dyn += struct.pack("<QQ", 1, i)
        dyn += struct.pack("<QQ", 0, 0)
    return hdr + ph0 + ph1 + dyn + dynstr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="ow-selftest-"))
    try:
        # ── A. ELF 解析 ────────────────────────────────────────────────
        for bits in (32, 64):
            p = tmp / ("elf%d.bin" % bits)
            p.write_bytes(make_elf(["libblas.so.3", "libm.so.6"], bits=bits))
            got = B._elf_needed(p)
            check("A%d DT_NEEDED %d 位解析" % (bits, bits),
                  got == ["libblas.so.3", "libm.so.6"], "得到 %s" % got)
        junk = tmp / "not-elf.txt"
        junk.write_text("hello")
        check("A0 非 ELF 返回空", B._elf_needed(junk) == [])

        # ── B. 系统库归属 ──────────────────────────────────────────────
        must_sys = ["libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2",
                    "ld-linux-x86-64.so.2", "libGL.so.1", "libX11.so.6", "libvulkan.so.1"]
        can_pack = ["libblas.so.3", "liblapack.so.3", "libgfortran.so.5", "libz.so.1",
                    "libjpeg.so.62", "libstdc++.so.6", "libgcc_s.so.1", "libwebp.so.7"]
        ok1 = all(B._is_system_only(x) for x in must_sys)
        ok2 = all(not B._is_system_only(x) for x in can_pack)
        check("B1 glibc/显卡家族必须由系统提供", ok1)
        check("B2 BLAS/编解码库应可打包", ok2)

        # ── C. 链式递归补齐 ───────────────────────────────────────────
        pkg = tmp / "chain" / "pkg"
        fake = tmp / "chain" / "fakesys"
        pkg.mkdir(parents=True)
        fake.mkdir(parents=True)
        (pkg / "ownrender").write_bytes(make_elf(["libA.so.1"]))
        (fake / "libA.so.1").write_bytes(make_elf(["libB.so.2"]))
        (fake / "libB.so.2").write_bytes(make_elf(["libc.so.6", "libz.so.1"]))
        real_find = B._find_system_lib
        B._find_system_lib = lambda so: (str(fake / so) if (fake / so).exists() else None)
        try:
            B._bundle_system_libs(pkg)
        finally:
            B._find_system_lib = real_find
        got = sorted(p.name for p in pkg.iterdir() if p.name.startswith("lib"))
        check("C1 链式递归补齐（libA→libB，libc 不打包）",
              got == ["libA.so.1", "libB.so.2"], "得到 %s" % got)
        check("C2 glibc 家族未被误打包", "libc.so.6" not in got)

        # 包内已有一律不误报：再跑一次，模拟"系统里没有"，应当零改动
        pkg2 = tmp / "chain" / "pkg2"
        shutil.copytree(pkg, pkg2)
        before = sorted(p.name for p in pkg2.iterdir())
        B._find_system_lib = lambda so: None
        try:
            B._bundle_system_libs(pkg2)
        finally:
            B._find_system_lib = real_find
        after = sorted(p.name for p in pkg2.iterdir())
        check("C3 包内已有库不误报、不重复复制", before == after)

        # ── D. Windows 找主程序（不能把 LICENSE 当 exe）───────────────
        wd = tmp / "win" / "OwnRender-windows-x64"
        wd.mkdir(parents=True)
        (wd / "LICENSE").write_text("license text")
        (wd / "README.md").write_text("readme")
        os.makedirs(wd / "libs", exist_ok=True)
        (wd / "libs" / "ownrender.exe").write_bytes(b"MZ" + b"\x00" * 32)
        found = V.find_exe(str(tmp / "win"))
        check("D1 Windows 选中真正的 ownrender.exe（不是 LICENSE）",
              found and Path(found).name.lower() == "ownrender.exe", "得到 %s" % found)

        # ── E. Android 验收 4 形态 ────────────────────────────────────
        def so_zip(path, with_p4a):
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("arm64-v8a/libpython3.10.so", b"\x7fELF" + b"\x00" * 32)
                z.writestr("arm64-v8a/libmain.so", b"\x7fELF" + b"\x00" * 32)
                z.writestr("arm64-v8a/libpybundle.so", gzip.compress(b"PK\x03\x04stub"))
                if with_p4a:
                    z.writestr("arm64-v8a/p4a-dist/site-packages/numpy/core/"
                               "_multiarray_umath.so", b"\x7fELF" + b"\x00" * 32)
                    z.writestr("arm64-v8a/p4a-dist/site-packages/PIL/_imaging.so",
                               b"\x7fELF" + b"\x00" * 32)

        def apk(path, with_bundle):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as t:
                names = (["_python_bundle/site-packages/numpy/core/_multiarray_umath.so",
                          "_python_bundle/site-packages/PIL/_imaging.so"]
                         if with_bundle else ["_python_bundle/README"])
                for nm in names:
                    data = b"\x7fELF" + b"\x00" * 32
                    ti = tarfile.TarInfo(nm)
                    ti.size = len(data)
                    t.addfile(ti, io.BytesIO(data))
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("AndroidManifest.xml", b"<manifest/>")
                z.writestr("lib/arm64-v8a/libpython3.10.so", b"\x7fELF" + b"\x00" * 32)
                z.writestr("assets/_python_bundle.tar.gz", gzip.compress(buf.getvalue()))

        def run_android(tag, so, apk_path):
            out = tmp / ("out_" + tag)
            cmd = [PY, str(ROOT / "tools" / "verify_package.py"), "--out-dir", str(out),
                   "--platform", "android", "--arch", "arm64-v8a"]
            if so:
                cmd += ["--android-so-zip", str(so)]
            if apk_path:
                cmd += ["--android-apk", str(apk_path)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return r.returncode, r.stdout

        z_plain = tmp / "so_plain.zip"
        so_zip(z_plain, with_p4a=True)
        rc, _ = run_android("plain", z_plain, None)
        check("E1 so.zip 里 p4a-dist 带 numpy/PIL → PASS", rc == 0, "exit=%d" % rc)

        z_bare = tmp / "so_bare.zip"
        so_zip(z_bare, with_p4a=False)
        a_ok = tmp / "app_ok.apk"
        apk(a_ok, with_bundle=True)
        rc, _ = run_android("apk_ok", z_bare, a_ok)
        check("E2 模块在 APK 内嵌归档里 → PASS", rc == 0, "exit=%d" % rc)

        a_bad = tmp / "app_bad.apk"
        apk(a_bad, with_bundle=False)
        rc, out = run_android("apk_bad", z_bare, a_bad)
        check("E3 哪里都没有 numpy/PIL → FAIL 且说清原因",
              rc == 1 and "numpy" in out, "exit=%d" % rc)

        rc, out = run_android("only_so", z_bare, None)
        check("E4 只给 so.zip（无 APK）→ FAIL", rc == 1, "exit=%d" % rc)

        # ── F. 文档与代码一致 ────────────────────────────────────────
        r = subprocess.run([PY, str(ROOT / "tools" / "gen_cli_doc.py"), "--check"],
                           capture_output=True, text=True)
        check("F1 docs/cli-args.json 与 CLI-参数.ai.md 与代码一致",
              r.returncode == 0, r.stdout.strip()[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [n for n, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 58)
    print("自测 %d 项：%d 通过 / %d 失败" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    if bad:
        for n in bad:
            print("  ❌ %s" % n)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())