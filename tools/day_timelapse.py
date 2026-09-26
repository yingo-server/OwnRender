#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键生成「全天延时」：按固定步长渲染一整天，再拼成视频。

默认行为（可直接跑）：
    每 3 分钟一张 → 24h 共 480 张 → 拼成 1 秒一张（1 fps）的视频。

产物（默认在 dist/timelapse/ 下）：
    frames/f0000_final.png …    每张图（文件名固定，便于 glob/续跑）
    day.mp4                     视频（1 张 = 1 秒）
    progress.json               进度（帧数/已完成/耗时/失败清单）

特性：
    · 断点续跑：已存在的帧直接跳过，中断后重跑不白干
    · 并行：--jobs N（默认 min(4, CPU)），每帧独立输出，安全
    · 失败重试：--retry N
    · 只调试：--limit 5 / --dry-run

用法示例：
    python tools/day_timelapse.py                       # 全天 3 分钟步长
    python tools/day_timelapse.py --date 2026-06-21 --bg 微水泥 --text 朝闻道
    python tools/day_timelapse.py --step-min 10 --resolution 1K --jobs 4
    python tools/day_timelapse.py --no-video --limit 6   # 只出 6 张试水
"""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import threading
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = dict(
    bg="微水泥", text="朝闻道", step_min=3, fps=1,
    resolution="2K", aspect="16:9", ssaa=1,
    # 天气是**物理输入**（云量/能见度/湿度/降水/气温）：必须显式钉死。
    # 不指定的话引擎会逐帧去查 Open-Meteo 实时天气 → 一整天可能"一会儿晴一会儿雨"。
    weather="clear",
    # 字体：不指定时引擎会 random.choice() 每帧随机换字体（视频里会乱跳），必须钉死。
    # 可选：AaXiuKai-2 / QuanHengDuLiang-v0.1 / 草檀斋毛泽东字体(8)
    font="AaXiuKai-2",
    # 纹理种子：钉死后玻璃污渍/灰尘/年代感在所有帧上完全一致，只有光照随时间变化
    seed=20260926,
    lat=39.9042, lon=116.4074, tz="+08:00",
    font_ratio=0.22, jobs=4, stagger=8, retry=2, out="",
)


def ensure_executable(exe):
    """/sdcard 在 Android 上是 FUSE(n)oexec 挂载，直接跑会 Permission denied。
    这里自动把包整份复制到可执行的缓存目录（~/.cache/ownrender-run/），再返回新路径。
    """
    if os.name == "nt":
        return exe
    if os.access(exe, os.X_OK):
        # 也可能挂在 noexec 上：真正试一下才能确定
        try:
            r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return exe
        except Exception:                            # noqa: BLE001
            pass
    cache = Path(os.path.expanduser("~/.cache/ownrender-run")) / exe.parent.name
    need_copy = (not cache.exists()) or (not os.access(cache / exe.name, os.X_OK))
    if need_copy:
        print("检测到该路径不可执行（/sdcard 是 noexec），复制一份到 %s" % cache)
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(exe.parent, cache, symlinks=True)
        os.chmod(cache / exe.name, 0o755)
    new_exe = cache / exe.name
    r = subprocess.run([str(new_exe), "--version"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.exit("可执行文件仍跑不起来：%s\n%s" % (new_exe, (r.stderr or r.stdout)[:400]))
    return new_exe


def find_engine(explicit=None):
    """找一个可用的 ownrender 可执行文件（优先 dist/ 下的包）。"""
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            p = p / ("ownrender.exe" if os.name == "nt" else "ownrender")
        if not p.exists():
            sys.exit("找不到可执行文件：%s" % p)
        return p
    cands = []
    cands += sorted(ROOT.glob("dist/OwnRender-*/ownrender"))
    if os.name == "nt":
        cands += sorted(ROOT.glob("dist/OwnRender-*/ownrender.exe"))
    for name in ("ownrender", "agnes-render"):
        w = shutil.which(name)
        if w:
            cands.append(Path(w))
    if not cands:
        sys.exit("没有找到 ownrender 可执行文件。\n"
                 "  请先下载对应架构的包并解压到 dist/，或用 --engine 指定路径。\n"
                 "  本机架构：%s（应下载 linux-aarch64 / linux-x86_64 里对应那个）"
                 % os.uname().machine)
    return cands[0]


def build_frames(args, engine, frames_dir, out_dir):
    """生成每一帧的 (index, 时刻, 目标文件, 命令)"""
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    n_day = 24 * 60 // args.step_min
    items = []
    for i in range(n_day):
        minutes = i * args.step_min
        hh, mm = divmod(minutes, 60)
        t = "%sT%02d:%02d:00%s" % (date, hh, mm, args.tz)
        name = "f%04d" % i
        target = frames_dir / ("%s_final.png" % name)
        cmd = [str(engine),
               "--offline-bg", args.bg,
               "-t", args.text,
               "--time", t,
               "--lat", str(args.lat), "--lon", str(args.lon),
               "-r", args.resolution, "-a", args.aspect,
               "--ssaa", str(args.ssaa),
               "--font-ratio", str(args.font_ratio),
               # 天气：物理输入（钉死，避免逐帧去查实时天气）
               "--weather", str(args.weather),
               "-o", str(frames_dir), "--output-name", name,
               "-y", "--no-color"]
        # 字体必须显式指定，否则引擎会 random.choice() 每帧换一个
        if args.font:
            cmd += ["-f", args.font]
        # 固定纹理种子：所有帧的玻璃/灰尘/年代感纹理一致，画面只随时间的光照变化
        if args.seed is not None:
            cmd += ["--seed", str(args.seed)]
        items.append((i, t, name, target, cmd))
    return items


def canonical(frames_dir, name, target):
    """引擎会产出 <name>_<日期时间>_final.png（中间插时间戳），
    这里统一改名成 <name>_final.png，便于后续 ffmpeg 按序拼帧。"""
    if target.exists() and target.stat().st_size > 0:
        return target
    cands = [p for p in sorted(frames_dir.glob("%s*_final.png" % name))
             if p.stat().st_size > 0]
    if not cands:
        return None
    if cands[0].name != target.name:
        os.replace(cands[0], target)          # 顺手清掉多出来的重复帧
    return target


FONTS_USED = set()
_FONTLOCK = threading.Lock()


def _note_font(text_out):
    """从引擎输出里抽「字体选择」块下的实际字体名，用于跑完自证全片字体一致。

    引擎输出形如：
        ==> 字体选择
          + AaXiuKai-2.ttf
    """
    lines = (text_out or "").splitlines()
    for i, ln in enumerate(lines):
        if "字体选择" in ln:
            for nxt in lines[i + 1:i + 4]:
                s = nxt.strip().lstrip("+·*-> ").strip()
                if s and not s.startswith("="):
                    with _FONTLOCK:
                        FONTS_USED.add(s)
                    return


def run_one(job, engine_dir, retry, quiet=True, dry=False):
    i, t, name, target, cmd = job
    if canonical(target.parent, name, target):
        return (i, t, "skip", 0.0, "")
    if dry:
        return (i, t, "dry", 0.0, " ".join(cmd))
    env = dict(os.environ)
    env.setdefault("OWNRENDER_NO_REEXEC", "1")
    env.setdefault("LC_ALL", "C.UTF-8")
    err = ""
    for attempt in range(retry + 1):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=str(engine_dir), env=env,
                               capture_output=True, text=True, timeout=900)
            got = canonical(target.parent, name, target)
            _note_font(r.stdout)
            if r.returncode == 0 and got:
                return (i, t, "ok", time.time() - t0, "")
            err = ("exit=%d | " % r.returncode) + (r.stderr or r.stdout or "")[-260:]
            err = err.replace("\n", " ")
        except Exception as e:                      # noqa: BLE001
            err = str(e)[:300]
        time.sleep(1.5 * (attempt + 1))
    return (i, t, "fail", time.time() - t0, err)


def make_video(frames_dir, out_mp4, fps, first="f%04d_final.png"):
    """把帧拼成视频：1 fps 输入 = 每张停 1 秒。

    两个环境差异要注意：
      · ffmpeg 跑在 Android 应用侧时看不到 proot 的路径 —— 所以帧目录尽量放在 /sdcard；
      · 该 ffmpeg 构建**没有 libx264**（只有 mpeg4 / vpx / av1），所以默认用 mpeg4。
    无论本机有没有 ffmpeg，都会写出 make_video.sh，方便直接用工具包执行。
    """
    local = shutil.which("ffmpeg")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] if local else ["-c:v", "mpeg4", "-q:v", "3"]
    cmd = [local or "ffmpeg", "-y",
           "-framerate", str(fps),
           "-i", str(frames_dir / first),
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           *enc, "-r", "30", "-movflags", "+faststart", str(out_mp4)]

    sh = frames_dir.parent / "make_video.sh"
    sh.write_text("#!/bin/sh\n# 把每天的帧拼成视频（每张 1 秒）\n"
                  "# 本机没装 ffmpeg 时，把下面这行丢给本 App 的 ffmpeg 工具包执行即可。\n"
                  + " ".join(cmd) + "\n", encoding="utf-8")
    sh.chmod(0o755)

    if not local:
        print("\n本机（proot）没有 ffmpeg，已生成拼帧脚本：%s" % sh)
        print("做法：把下面这条命令交给 App 的 ffmpeg 工具包执行（注意用 /sdcard 路径）：")
        print("  " + " ".join(cmd))
        return None, cmd
    print("\n拼视频：%s" % " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg 失败（可用 %s 换编码器重试）：\n%s" % (sh, (r.stderr or "")[-1000:]))
        return None, cmd
    return out_mp4, cmd


def main():
    ap = argparse.ArgumentParser(description="全天延时：3 分钟一张 → 1 秒一张的视频")
    ap.add_argument("--engine", help="ownrender 可执行文件或包目录（默认自动找 dist/）")
    ap.add_argument("--bg", default=DEFAULTS["bg"], help="内置底图名（默认 微水泥）")
    ap.add_argument("--text", default=DEFAULTS["text"], help="文案（默认 朝闻道）")
    ap.add_argument("--date", help="日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--step-min", type=int, default=DEFAULTS["step_min"], help="步长分钟（默认 3）")
    ap.add_argument("--tz", default=DEFAULTS["tz"], help="时区偏移（默认 +08:00）")
    ap.add_argument("--lat", type=float, default=DEFAULTS["lat"])
    ap.add_argument("--lon", type=float, default=DEFAULTS["lon"])
    ap.add_argument("-r", "--resolution", default=DEFAULTS["resolution"], help="1K/2K/3K/4K")
    ap.add_argument("-a", "--aspect", default=DEFAULTS["aspect"], help="如 16:9 / 9:16 / 1:1")
    ap.add_argument("--ssaa", type=int, default=DEFAULTS["ssaa"], help="超采样（默认 1，提速）")
    ap.add_argument("--font-ratio", type=float, default=DEFAULTS["font_ratio"],
                    help="字号占画面高度比例（默认 0.22）")
    ap.add_argument("--weather", default=DEFAULTS["weather"],
                    help="天气（物理输入：云量/能见度/湿度/降水/气温；默认 clear）")
    ap.add_argument("--font", default=DEFAULTS["font"],
                    help="字体名（钉死用，避免引擎每帧随机换字体；默认 AaXiuKai-2）")
    ap.add_argument("--seed", type=int, default=DEFAULTS["seed"],
                    help="纹理种子（固定后所有帧纹理一致；默认 20260926）")
    ap.add_argument("--fps", type=int, default=DEFAULTS["fps"], help="视频帧率（默认 1＝每张 1 秒）")
    ap.add_argument("--jobs", type=int, default=DEFAULTS["jobs"],
                    help="同时在跑的帧数（默认 4）")
    ap.add_argument("--stagger", type=int, default=DEFAULTS["stagger"],
                    help="错峰启动：每 N 秒起一个新帧（默认 8，避免 4 个重任务同时抢 CPU；0=不限制）")
    ap.add_argument("--retry", type=int, default=DEFAULTS["retry"], help="单帧失败重试次数")
    ap.add_argument("--out", default=DEFAULTS["out"], help="输出根目录（默认 dist/timelapse）")
    ap.add_argument("--limit", type=int, help="只生成前 N 帧（调试）")
    ap.add_argument("--no-video", action="store_true", help="只出帧，不拼视频")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令")
    a = ap.parse_args()

    engine = find_engine(a.engine)
    engine = ensure_executable(engine)
    engine_dir = engine.parent
    out_dir = Path(a.out) if a.out else (ROOT / "dist" / "timelapse")
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    jobs_n = a.jobs or 4

    # ── 字体预检：参数模式下引擎会在缺省时 random.choice()，这里必须确认字体确切存在 ──
    r = subprocess.run([str(engine), "--list-fonts", "--no-color"],
                       capture_output=True, text=True, timeout=180)
    avail = []          # 同时收集 "含后缀" 与 "去后缀" 两种写法
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if s.startswith("[") and "]" in s:
            rest = s.split("]", 1)[1].strip().split()
            if rest:
                avail.append(rest[0])
                avail.append(os.path.splitext(rest[0])[0])
    if a.font:
        if avail and a.font not in avail:
            sys.exit("字体 %r 不存在。可用：%s\n（用 --font 指定其一）"
                     % (a.font, " / ".join(sorted(set(avail)))))
        print("字体校验  ：✓ %s 在包内（共 %d 个可用）" % (a.font, len(avail)))
    else:
        print("字体校验  ：⚠ 未指定 --font → 引擎会逐帧随机挑字体，视频将不一致")

    items = build_frames(a, engine, frames_dir, out_dir)
    total = len(items)
    if a.limit:
        items = items[:a.limit]
    done_before = sum(1 for _, _, _, tgt, _ in items if tgt.exists())
    print("引擎      ：%s" % engine)
    print("底图/文案 ：%s / %s / 天气=%s" % (a.bg, a.text, a.weather))
    print("日期/步长 ：%s 每 %d 分钟（共 %d 帧，本机已存在 %d 帧）"
          % (a.date or "今天", a.step_min, total, done_before))
    print("规格      ：%s %s ssaa=%d 字号=%s" % (a.resolution, a.aspect, a.ssaa, a.font_ratio))
    print("字体/种子 ：%s   seed=%s（全片钉死，避免逐帧随机）" % (a.font or "（随机！）", a.seed))
    print("时序      ：最多 %d 个同时跑；起步每 %d 秒放一个；之后完成一个才补一个"
          % (jobs_n, a.stagger))
    print("输出      ：%s\n" % out_dir)

    result = {"engine": str(engine), "bg": a.bg, "text": a.text,
              "date": a.date, "step_min": a.step_min, "total": total,
              "frames_dir": str(frames_dir), "started": datetime.now().isoformat(timespec="seconds"),
              "ok": 0, "skip": 0, "fail": 0, "failed": []}
    prog = out_dir / "progress.json"
    prog.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    t_start = time.time()
    fails = []
    timeline_path = out_dir / "timeline.tsv"
    tl = open(timeline_path, "w", encoding="utf-8")
    tl.write("index\ttime\tstatus\tsecs\tfinished_at\n")

    # 时序规划：
    #   · 最多 jobs_n 个帧同时在跑（不预先把 480 个丢进去抢 CPU）
    #   · 起步阶段每 stagger 秒才放一个新帧进去 —— 避免 4 个重任务同时开始
    #   · 之后每完成一帧才补下一帧（自然错峰，不做突发批量）
    with cf.ThreadPoolExecutor(max_workers=jobs_n) as ex:
        futs = {}
        pending = list(items)
        started = 0
        while pending or futs:
            while pending and len(futs) < jobs_n:
                # 只有"起步那几帧"需要人为错峰；之后的补位由完成事件驱动
                if 0 < started < jobs_n and a.stagger > 0:
                    time.sleep(a.stagger)
                it = pending.pop(0)
                fut = ex.submit(run_one, it, engine_dir, a.retry, True, a.dry_run)
                futs[fut] = it
                started += 1
            if not futs:
                break
            done, _ = cf.wait(list(futs), return_when=cf.FIRST_COMPLETED)
            for fut in done:
                it = futs.pop(fut)
                i, t, status, secs, err = fut.result()
                if status == "ok":
                    result["ok"] += 1
                elif status == "skip":
                    result["skip"] += 1
                elif status == "fail":
                    result["fail"] += 1
                    fails.append({"index": i, "time": t, "err": err})
                n = result["ok"] + result["skip"] + result["fail"]
                el = time.time() - t_start
                tl.write("%04d\t%s\t%s\t%.1f\t%s\n"
                         % (i, t, status, secs,
                            datetime.now().strftime("%H:%M:%S")))
                tl.flush()
                if n % 10 == 0 or n == len(items):
                    rate = n / el if el else 0
                    eta = (len(items) - n) / rate if rate else 0
                    print("[%3d/%3d] %.1f 帧/分  已用 %.1f 分  预计剩余 %.1f 分  失败 %d  在跑 %d"
                          % (n, len(items), rate * 60, el / 60, eta / 60,
                             result["fail"], len(futs)), flush=True)
                result["failed"] = fails[:50]
                result["elapsed_sec"] = round(el, 1)
                prog.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tl.close()

    made = sorted(p for p in frames_dir.glob("f*_final.png"))
    fonts = sorted(FONTS_USED)
    result["fonts_used"] = fonts
    print("\n字体自证  ：实际使用字体 %s —— %s"
          % (fonts or "（未捕获）",
             "✓ 全片一致" if len(fonts) <= 1 else "✗ 不一致，视频会乱跳！"))
    print("\n生成完成：%d 帧可用（新生成 %d / 跳过 %d / 失败 %d），用时 %.1f 分钟"
          % (len(made), result["ok"], result["skip"], result["fail"], (time.time() - t_start) / 60))
    if fails:
        print("失败清单（前 5）：")
        for f in fails[:5]:
            print("  #%d %s — %s" % (f["index"], f["time"], f["err"]))

    if not a.no_video and made:
        out_mp4 = out_dir / "day.mp4"
        got, cmd = make_video(frames_dir, out_mp4, a.fps)
        if got:
            size = Path(got).stat().st_size / 1048576
            print("视频：%s（%.1f MB，%d 张 × 1/%.1f 秒）" % (got, size, len(made), a.fps))
        else:
            print("（视频未生成；帧都在 %s）" % frames_dir)
    return 0 if result["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())