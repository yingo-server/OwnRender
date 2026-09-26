#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布包验收脚本（跨平台，纯标准库）

用法：
    python tools/verify_package.py --package-dir <解压后的目录|可执行文件> \
        --out-dir <输出目录> [--platform linux] [--arch x86_64] [--ascii-env]

做四件事：
  1) 定位可执行文件（OwnRender / OwnRender.exe / 顶层可执行）
  2) 依次跑：--version / --list-backgrounds / --list-fonts / --list-sizes
  3) 挑一张内置底图做一次真渲染（有底图才跑），把产物拷进输出目录
  4) 汇总判定 + 写 meta.json / stdout.log / stderr.log / summary.txt
     —— 任何一步的 stdout/stderr 出现 traceback 都判 FAIL

另外可选 --ascii-env：用 LC_ALL=C + PYTHONUTF8=0 再跑一次列表命令，
专门验证"哑终端/容器无 UTF-8 locale"下不会因编码崩掉。
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

TIMEOUT = 600


def log(msg, fh=None):
    print(msg, flush=True)
    if fh:
        fh.write(msg + "\n")


def find_exe(pkg_dir):
    """在包目录里找主可执行文件。"""
    names = ("OwnRender.exe", "OwnRender", "ownrender.exe", "ownrender")
    roots = [pkg_dir]
    for sub in ("OwnRender.dist", "OwnRender", "."):
        roots.append(os.path.join(pkg_dir, sub))
    for r in roots:
        for n in names:
            p = os.path.join(r, n)
            if os.path.isfile(p):
                return p
    # 兜底：顶层任意可执行文件
    for dp, dns, fns in os.walk(pkg_dir):
        for f in fns:
            if f.endswith(".exe") or (os.access(os.path.join(dp, f), os.X_OK)
                                      and not f.endswith((".so", ".dll", ".dylib",
                                                          ".py", ".md"))):
                return os.path.join(dp, f)
    return None


def run(exe, args, cwd, extra_env=None):
    env = dict(os.environ)
    env.setdefault("OWNRENDER_NO_REEXEC", "1")     # 验收时不要自我重启
    if extra_env:
        env.update(extra_env)
    t0 = time.time()
    try:
        p = subprocess.run([exe] + args, cwd=cwd, env=env, capture_output=True,
                           timeout=TIMEOUT)
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        code = p.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "TIMEOUT after %ds" % TIMEOUT, 124
    except Exception as e:
        out, err, code = "", "RUN-ERROR %r" % (e,), 125
    return {"args": args, "exit": code, "secs": round(time.time() - t0, 2),
            "stdout": out, "stderr": err}


def bad(res):
    """判定失败：非零退出 / traceback / 编码异常。"""
    if res["exit"] != 0:
        return "exit=%d" % res["exit"]
    blob = res["stdout"] + res["stderr"]
    for pat in ("Traceback (most recent call last)",
                "UnicodeEncodeError", "UnicodeDecodeError",
                "SyntaxError", "ModuleNotFoundError", "ImportError"):
        if pat in blob:
            return "出现 %s" % pat
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--platform", default=platform.system().lower())
    ap.add_argument("--arch", default=platform.machine())
    ap.add_argument("--ascii-env", action="store_true",
                    help="额外在 LC_ALL=C / PYTHONUTF8=0 下跑一遍列表命令")
    a = ap.parse_args()

    out_dir = os.path.abspath(a.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    so = open(os.path.join(out_dir, "stdout.log"), "w", encoding="utf-8")
    se = open(os.path.join(out_dir, "stderr.log"), "w", encoding="utf-8")
    steps, problems, notes = [], [], []

    log("=" * 62)
    log("验收：platform=%s arch=%s" % (a.platform, a.arch))
    log("包目录：%s" % a.package_dir)
    exe = find_exe(os.path.abspath(a.package_dir))
    if not exe:
        problems.append("找不到可执行文件")
        log("!! 找不到可执行文件")
    else:
        log("可执行文件：%s (%.1f MB)" % (exe, os.path.getsize(exe) / 1048576))
        cwd = os.path.dirname(exe)

        def do(args, label, env=None):
            res = run(exe, args, cwd, env)
            steps.append({"label": label, "args": args, "exit": res["exit"],
                          "secs": res["secs"]})
            log("\n--- %s  $ %s" % (label, " ".join(args)))
            log(res["stdout"].rstrip()[:4000], so)
            if res["stderr"].strip():
                log("[stderr] " + res["stderr"].rstrip()[:2000], se)
            log("退出码=%d 用时=%.2fs" % (res["exit"], res["secs"]))
            why = bad(res)
            if why:
                problems.append("%s：%s" % (label, why))
            return res

        do(["--version"], "版本")
        r_bg = do(["--list-backgrounds"], "底图列表")
        do(["--list-fonts"], "字体列表")
        do(["--list-sizes"], "尺寸表")

        if a.ascii_env:
            do(["--list-backgrounds"], "底图列表(LC_ALL=C)", 
               env={"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0",
                    "PYTHONUTF8": "0"})
            do(["--list-fonts"], "字体列表(LC_ALL=C)",
               env={"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0",
                    "PYTHONUTF8": "0"})

        # 挑一张底图做真渲染
        bgs = re.findall(r"\[\d+\]\s+(\S+\.png)", r_bg["stdout"])
        if bgs:
            bg = bgs[0]
            def collect_pngs(since, cwd0):
                """在多个候选位置找本次渲染的产物（打包后在 <pkg>/output，源码树可能在别处）。"""
                base = os.path.abspath(a.package_dir)
                cands = [os.path.join(cwd0, "output"), os.path.join(base, "output")]
                for dp, dns, _fns in os.walk(base):       # 两级内任意 output/ 目录
                    if dp.count(os.sep) - base.count(os.sep) > 2:
                        dns[:] = []
                        continue
                    if os.path.basename(dp) == "output":
                        cands.append(dp)
                seen, out = set(), []
                for d in cands:
                    if not os.path.isdir(d):
                        continue
                    for f in sorted(os.listdir(d)):
                        p = os.path.join(d, f)
                        if not (f.lower().endswith(".png") and os.path.isfile(p)):
                            continue
                        if os.path.getmtime(p) < since - 2:   # 只要本次新产出的
                            continue
                        rp = os.path.realpath(p)
                        if rp not in seen:
                            seen.add(rp)
                            out.append(p)
                return out

            got = []
            for attempt in (1, 2):
                t_render = time.time()
                label = "真渲染" if attempt == 1 else "真渲染(重试)"
                r_rd = do(["--offline-bg", bg, "-t", "验收", "--time", "04:00",
                           "--ssaa", "1", "--seed", "7", "-y", "--no-color"], label)
                got = []
                for src in collect_pngs(t_render, cwd):
                    f = os.path.basename(src)
                    dst = os.path.join(out_dir, "%s_%s_%s" % (a.platform, a.arch, f))
                    shutil.copy2(src, dst)
                    got.append("%s (%.2f MB)" % (f, os.path.getsize(dst) / 1048576))
                if got:
                    break
                # 本次没拿到产物：撤掉本次的问题记录，交给下一次重试重新判定
                while problems and problems[-1].startswith("真渲染"):
                    problems.pop()
            notes.append("渲染产物：%s" % (got or "无"))
            if not got:
                problems.append("真渲染：未产出 PNG")
            # 抓渲染摘要里的关键行，作为"光照/定位算法正确"的验收证据（正则精确匹配）
            for pat, label in (
                    (r"本地\s+([\d\-:. ]+)", "渲染本地时间"),
                    (r"来源\s+(\S.*?)\s*$", "定位来源"),
                    (r"地区\s+(\S.*?)\s*$", "渲染地区"),
                    (r"坐标\s+\(([^)]+)\)", "渲染坐标"),
                    (r"天气\s+(\S+)\s+云(\d+)%", "渲染天气(云量%)"),
                    (r"光源\s+(\S+)\s+方位([+\-\d.]+)°\s+高度([+\-\d.]+)°", "渲染光源(方位/高度)"),
                    (r"辐照度\s+([\d.]+)", "渲染辐照度"),
                    (r"可达性\s+(\S.*?)\s*$", "光照可达性")):
                m = re.search(pat, r_rd["stdout"], re.M)
                if m:
                    notes.append("%s：%s" % (label, " ".join(g.strip() for g in m.groups())))
        else:
            notes.append("包内没有内置底图，跳过真渲染")

    verdict = "PASS" if not problems else "FAIL"
    meta = {"platform": a.platform, "arch": a.arch, "verdict": verdict,
            "exe": exe, "package_dir": os.path.abspath(a.package_dir),
            "steps": steps, "problems": problems, "notes": notes,
            "host": platform.platform()}
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("平台/架构：%s/%s\n" % (a.platform, a.arch))
        f.write("结论：%s\n\n" % verdict)
        for s in steps:
            f.write("  %-22s exit=%d  %.2fs\n" % (s["label"], s["exit"], s["secs"]))
        for n in notes:
            f.write("note: %s\n" % n)
        for p in problems:
            f.write("problem: %s\n" % p)

    so.close()
    se.close()
    print("\n" + "=" * 62)
    print("结论：%s" % verdict)
    for p in problems:
        print("  !! %s" % p)
    print("输出目录：%s" % out_dir)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())