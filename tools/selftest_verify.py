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
        # 把 stderr 也带上：缺依赖时是崩溃（stderr），只看 stdout 会"详情为空"
        detail = (r.stdout.strip() + " " + r.stderr.strip()).strip()[-300:]
        check("F1 docs/cli-args.json 与 CLI-参数.ai.md 与代码一致",
              r.returncode == 0, detail)

        # ── G. 大气/天气物理（frame_light/atmosphere.py）─────────────
        # 这些是"参数必须真实"的守门测试：物理量必须单调/守恒/有界。
        sys.path.insert(0, str(ROOT))
        import importlib
        import frame_light.astro as A
        import frame_light.atmosphere as ATM
        importlib.reload(A)
        importlib.reload(ATM)

        # G1 云 → 直射透过率：单调递减，两端值符合物理
        t = [ATM.direct_transmittance(c) for c in (0, 25, 50, 75, 85, 100)]
        check("G1 云透过率单调递减且 T(0)=1/T(100)≈5%",
              all(t[i] > t[i + 1] for i in range(len(t) - 1))
              and abs(t[0] - 1.0) < 1e-9 and 0.03 < t[-1] < 0.08,
              " ".join("%.3f" % v for v in t))

        # G2 云修正因子：单调递减，全阴≈1/4（实测世界 20%~30%）
        cmf = [ATM.cloud_modification(c) for c in (0, 50, 85, 100)]
        check("G2 云修正因子单调递减且全阴≈0.25",
              all(cmf[i] > cmf[i + 1] for i in range(len(cmf) - 1))
              and abs(cmf[0] - 1.0) < 1e-9 and 0.2 < cmf[-1] < 0.3,
              " ".join("%.3f" % v for v in cmf))

        # G3 直射/漫射分离：晴天守恒（漫射不低于晴空），全阴几乎全是漫射
        b0, d0 = ATM.split_irradiance(0.82, 0.186, 48.0, 0)
        b1, d1 = ATM.split_irradiance(0.82, 0.186, 48.0, 100)
        check("G3 晴天直射≈晴空值且漫射不被吞掉",
              abs(b0 - 0.82) < 0.02 and abs(d0 - 0.186) < 0.02,
              "beam=%.3f diffuse=%.3f" % (b0, d0))
        check("G4 厚阴天直射几乎消失、漫射占主导",
              b1 < 0.1 and d1 > 3 * b1, "beam=%.3f diffuse=%.3f" % (b1, d1))

        # G5 地面反照率：雪 > 干 > 湿（物理）
        check("G5 地面反弹 雪(0.80) > 干(0.25) > 湿(0.07)",
              ATM.ground_bounce(-3, 3.0) > ATM.ground_bounce(20, 0.0)
              > ATM.ground_bounce(20, 2.0) > 0.0,
              "%.2f/%.2f/%.2f" % (ATM.ground_bounce(-3, 3.0),
                                  ATM.ground_bounce(20, 0.0),
                                  ATM.ground_bounce(20, 2.0)))
        check("G6 雪天判定需要气温 < 2℃（旧版缺 temp → 雪被判成雨）",
              ATM.ground_state(-3, 3.0) == "snow"
              and ATM.ground_state(20, 3.0) == "wet",
              ATM.ground_state(-3, 3.0) + "/" + ATM.ground_state(20, 3.0))

        # G7 水膜 / 空气光：单调有界，且室内空气光必须很小（诚实）
        wf = [ATM.water_film(p) for p in (0, 0.5, 2.0, 20.0)]
        check("G7 水膜覆盖率单调饱和在 [0,1]",
              all(0.0 <= v <= 1.0 for v in wf)
              and all(wf[i] <= wf[i + 1] for i in range(len(wf) - 1))
              and wf[0] == 0.0 and wf[-1] >= 0.99,
              " ".join("%.2f" % v for v in wf))
        check("G8 室内空气光很小（雾天 600m / 4m 光程 < 5%）",
              ATM.airlight_fraction(600, 4.0) < 0.05,
              "%.4f" % ATM.airlight_fraction(600, 4.0))

        # G9 视觉适应：照度越低补偿越大；夜间=1（夜就是夜）
        e_day = ATM.eye_exposure_ev(0.19, 1.0, 45.0)
        e_brt = ATM.eye_exposure_ev(1.00, 1.0, 45.0)
        check("G9 曝光适应：阴天 >1、晴天≈1、夜间=1",
              e_day > 1.2 and abs(e_brt - 1.0) < 0.05
              and ATM.eye_exposure_ev(0.02, 1.0, -5.0) == 1.0,
              "%.2f/%.2f" % (e_day, e_brt))

        # G10 WMO 天气码分类（雷阵雨/阵雨/雪 不能被当成普通雨）
        check("G10 WMO 码分类 95→雷阵雨 80→阵雨 73→雪",
              A.categorize_code(95) == "thunder"
              and A.categorize_code(80) == "shower"
              and A.categorize_code(73) == "snow",
              "%s/%s/%s" % (A.categorize_code(95), A.categorize_code(80),
                            A.categorize_code(73)))

        # G11 阵雨间歇性：确定性（可复现）且有起伏
        import datetime as _dt
        vs = [A.shower_dynamics(
            _dt.datetime(2026, 9, 26, hh, 0), 70, 0.6, "shower")[0]
            for hh in range(0, 24, 2)]
        again = A.shower_dynamics(
            _dt.datetime(2026, 9, 26, 8, 0), 70, 0.6, "shower")[0]
        check("G11 阵雨云量随时间起伏、且可复现",
              (max(vs) - min(vs)) > 20.0 and abs(again - vs[4]) < 1e-9,
              "范围 %.0f~%.0f" % (min(vs), max(vs)))

        # G12 全局手调参数 ≤ 5（架构约束，防止再退化成"调色表"）
        TUNABLES = ["EYE_ADAPT_GAMMA", "TAU_CLOUD_THICK", "WATER_FILM_REF_MM",
                    "GROUND_ALBEDO", "TONE_S_CURVE_GAIN"]
        extra = [n for n in dir(ATM)
                 if n.isupper() and not n.startswith("_")
                 and n not in TUNABLES
                 and n not in ("KOSCHMIEDER_K", "TWILIGHT_ALT_DEG")]
        check("G12 全局手调参数 ≤5 且无隐藏可调量",
              len(TUNABLES) <= 5 and not extra,
              "多出来的：%s" % extra)

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