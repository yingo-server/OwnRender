#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 主编排（重建版）

职责：
  1. run(argv)     — 唯一入口：解析 → 分发 → 菜单循环
  2. 主菜单         — 三种模式 + 设置 + 信息 + 退出
  3. 交互模式       — 统一走参数向导（wizard），可任意回退修改
  4. 非交互模式     — -y / 纯命令行：直接跑，行为与旧版一致

只 import config + tui + cli + settings + wizard + offline + ai。
"""
import sys

import config
from . import tui as T
from . import cli
from . import settings as st
from . import offline
from . import ai
from . import wizard


# ═══════════════════════════════════════════════════════════════════
# 外观
# ═══════════════════════════════════════════════════════════════════
def _banner():
    w = min(T.cols(), 76)
    T.blank()
    print(T.grey("┌" + "─" * (w - 2) + "┐"))
    line1 = (T.bold(T.cyan("  agnes-render")) + T.dim("  ·  物理光照墙面渲染"))
    line2 = T.dim(f"  v{config.VERSION}   "
                  f"底图 {len(offline.list_bgs())} 张   "
                  f"字体 {_n_fonts()} 个   "
                  f"模式 AI / 离线 / 自定义")
    print(T.grey("│") + line1 + " " * max(0, w - 3 - T._vis_len(line1))
          + T.grey("│"))
    print(T.grey("│") + line2 + " " * max(0, w - 3 - T._vis_len(line2))
          + T.grey("│"))
    print(T.grey("└" + "─" * (w - 2) + "┘"))


def _n_fonts():
    n = 0
    for ext in config.FONT_EXTENSIONS:
        n += len(list(config.FONT_DIR.glob(f"*{ext}")))
    return n


# ═══════════════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════════════
def main_menu() -> str:
    _banner()
    c = T.menu("主菜单", [
        "AI 生成底图 + 叠字          （在线，需要 Token）",
        "内置底图 + 物理光照 + 叠字   （离线）",
        "自定义图片 + 叠字            （离线，不光照）",
        "设置",
        "信息 / 环境自检",
        "退出",
    ], default=1, keys={"a": 0, "b": 1, "c": 2, "s": 3, "i": 4, "q": 5})
    return ["ai", "bg", "custom", "settings", "info", "exit"][c]


# ═══════════════════════════════════════════════════════════════════
# 单次运行
# ═══════════════════════════════════════════════════════════════════
def _run_mode(mode, args, interactive, image_path=None):
    """跑一次生成。interactive=True 时先过参数向导。"""
    if interactive:
        P = wizard.plan_from_args(args, mode, config.get_defaults())
        title = {"ai": "AI 生成 · 参数向导",
                 "bg": "离线光照 · 参数向导",
                 "custom": "自定义图片 · 参数向导"}[mode]
        try:
            if not wizard.run(P, title_text=title):
                T.warn("已放弃本次生成")
                return 0
        except T.Abort:
            T.blank()
            T.warn("已取消")
            return 130
        P.apply_runtime()
        P.apply_args(args)
    else:
        # 非交互：材质耦合 / 曝光 / 饱和度 取命令行 > 设置值
        try:
            d = config.get_defaults()
        except Exception:
            d = {}
        mc = getattr(args, "material_coupling", None)
        config.TEXT_MATERIAL_COUPLING = float(
            mc if mc is not None else d.get("material_coupling", 0.0) or 0.0)
        if getattr(args, "exposure", None) is not None:
            config.VISUAL_EXPOSURE = float(args.exposure)
        if getattr(args, "saturation", None) is not None:
            config.VISUAL_SATURATION = float(args.saturation)

    try:
        if mode == "custom":
            from pathlib import Path
            return offline.run_custom_image_generate(
                args, Path(str(image_path)), interactive=False)
        if mode == "bg":
            return offline.run_bg_lit_generate(args, interactive=False)
        return ai.run_ai_generate(args, interactive=False)
    except T.Abort:
        T.blank()
        T.warn("已取消")
        return 130


def _ask_image_path(args):
    from pathlib import Path
    if args.input_image:
        return args.input_image
    while True:
        s = T.ask("图片路径", "", allow_empty=True)
        if not s:
            return None
        p = Path(s).expanduser()
        if p.exists():
            return str(p)
        T.err(f"不存在: {p}")


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════
def run(argv=None) -> int:
    # 终端编码兼容：C/POSIX locale（最小化容器 / LANG=C 的服务器）下 stdout 是
    # ascii，打印中文或 ◆ 会直接崩；Windows 重定向输出也会遇到同类问题。
    # 这里统一处理：能修则强制 UTF-8，终端认不了 Unicode 符号就整体降级成 ASCII。
    config.ensure_utf8_stdio()

    T.init_term()
    T.init_color(force=True if "--no-color" not in (argv or sys.argv[1:])
                 else False)
    if "--no-color" in (argv or sys.argv[1:]):
        T.init_color(force=False)

    if argv is None:
        argv = [a for a in sys.argv[1:] if a != "--no-color"]
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    cli.normalize_args(args)

    # 日志
    d = config.get_defaults()
    _mode0 = cli.detect_mode(args)
    lv = args.log_level or d.get("log_level", "INFO")
    # 交互菜单下默认压低日志噪音（保持 TUI 干净）
    if _mode0 == "menu" and args.log_level is None and not args.verbose:
        lv = "WARN"
    log_file = ((config.LOG_DIR / "agnes-render.log")
                if (args.log_file or d.get("log_to_file", False)) else None)
    config.LOG.configure(level=lv, log_file=log_file)
    if args.verbose and args.log_level is None:
        config.LOG.level = config.Logger.LEVELS["DEBUG"]

    # 查询命令（不进入菜单）
    if args.list_fonts:       return st.cmd_list_fonts() or 0
    if args.list_backgrounds: return st.cmd_list_backgrounds() or 0
    if args.list_ntp:         return st.cmd_list_ntp() or 0
    if args.list_services:    return st.cmd_list_services() or 0
    if args.list_sizes:       return st.cmd_list_sizes() or 0
    if args.show_config:      return st.cmd_show_config() or 0
    if args.reset_config:     return st.cmd_reset_config() or 0
    if args.settings:
        st.settings_root()
        return 0

    # --set-location "lat,lon[,city]"：写本机定位缓存后退出
    if getattr(args, "set_location", None):
        from frame_light import astro as _astro
        try:
            parts = [p.strip() for p in args.set_location.split(",")]
            lat, lon = float(parts[0]), float(parts[1])
            city = parts[2] if len(parts) > 2 else ""
            if _astro.save_device_location(lat, lon, city, "cli"):
                T.ok(f"已存为本机定位 ({lat}, {lon}) {city}")
                return 0
            T.err("写入失败")
        except Exception as e:
            T.err(f"格式错误（应为 lat,lon[,city]）: {e}")
        return 1

    if args.seed is not None:
        import random
        random.seed(args.seed)
    config.LOG.info(f"{config.PROG} {config.VERSION} 启动")

    config.BG_DIR.mkdir(parents=True, exist_ok=True)
    config.FONT_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    mode = cli.detect_mode(args)
    interactive = not args.yes

    # ── 明确指定模式：直接跑 ──
    if mode != "menu":
        if mode == "custom" and not args.input_image:
            return 0
        return _run_mode(mode, args, interactive,
                         image_path=args.input_image)

    # ── 菜单循环 ──
    # 非交互终端下不进入 TUI（被当作库/被 CI 调用时，避免卡住）
    try:
        _tty = sys.stdin.isatty()
    except Exception:
        _tty = False
    if not _tty:
        print(f"{config.PROG} {config.VERSION}")
        print("未指定参数且当前不是交互终端 —— 已切换为「参数模式」。")
        print("完整参数见: --help 或 docs/命令行参数.md\n")
        parser.print_help()
        return 2

    while True:
        try:
            action = main_menu()
        except T.Abort:
            T.blank()
            return 0
        if action == "exit":
            T.blank()
            print(T.green("  ✓ 再见"))
            config.LOG.info("退出")
            return 0
        if action == "settings":
            st.settings_root()
            continue
        if action == "info":
            st.info_menu()
            continue
        path = None
        if action == "custom":
            path = _ask_image_path(args)
            if not path:
                T.warn("未提供图片")
                continue
        _run_mode(action, args, interactive=True, image_path=path)
        T.blank()
        T.info("回到主菜单")