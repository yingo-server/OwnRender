#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — CLI 参数解析

职责：
  1. build_parser() — argparse 解析器
  2. detect_mode(args) — 判断走 ai / offline / custom / menu
  3. has_generate_args(args) — 是否含生成参数

只 import config + utils（本框架）+ 标准库。
"""
import argparse
import textwrap

import config


# ═══════════════════════════════════════════════════════════════════
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=config.PROG,
        description=f"Agnes Render Engine V{config.VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        三种模式:
          [1] AI 生成底图 + 叠字             默认 / --ai
          [2] 内置底图 + 算法光照 + 叠字     --offline-bg NAME
          [3] 自定义图片 + 叠字               -i PATH

        示例:
          agnes-render
          agnes-render -t "谎如昨日，嗤笑今朝" -y
          agnes-render --offline-bg wall_gray -y
          agnes-render --offline-bg wall_gray \\
                       --time "2024-06-21 12:00" \\
                       --lat 39.9 --lon 116.4 --weather clear -y
          agnes-render -i /path/img.png -y
        """),
    )

    g = p.add_argument_group("模式选择")
    g.add_argument("--ai", action="store_true")
    g.add_argument("--offline-bg", metavar="NAME")
    g.add_argument("-i", "--input-image", metavar="PATH")
    g.add_argument("--background", metavar="NAME")
    g.add_argument("--keep-lit", action="store_true")

    g = p.add_argument_group("输入输出")
    g.add_argument("-t", "--text")
    g.add_argument("-o", "--output")
    g.add_argument("--output-name")

    g = p.add_argument_group("字体与位置")
    g.add_argument("-f", "--font")
    g.add_argument("--font-ratio", type=float, default=None)
    g.add_argument("--font-anchor", choices=config.ANCHORS, default=None)
    g.add_argument("--font-pos-x", type=float, default=None)
    g.add_argument("--font-pos-y", type=float, default=None)

    g = p.add_argument_group("窗户几何")
    g.add_argument("--window-orientation",
                   choices=config.WINDOW_ORIENTATIONS, default=None)
    g.add_argument("--window-side", choices=["left", "right"], default=None,
                   help=argparse.SUPPRESS)
    g.add_argument("--window-scale", type=float, default=None)
    g.add_argument("--grid-rows", type=int, default=None)
    g.add_argument("--grid-cols", type=int, default=None)
    g.add_argument("--grid-frame", type=float, default=None)
    g.add_argument("--shadow-length", default=None)

    g = p.add_argument_group("时间与位置")
    g.add_argument("--time")
    g.add_argument("--lat", type=float)
    g.add_argument("--lon", type=float)
    g.add_argument("--city")
    g.add_argument("--no-ntp", action="store_true")
    g.add_argument("--ntp-host")
    g.add_argument("--no-gps", action="store_true")
    g.add_argument("--geo-service")
    g.add_argument("--gps", action="store_true",
                   help="强制使用本机 GPS（termux-location/系统接口/缓存）")
    g.add_argument("--ip-loc", action="store_true",
                   help="强制使用 IP 网络定位")
    g.add_argument("--set-location", metavar="LAT,LON[,CITY]",
                   help="把坐标写入本机定位缓存，供以后一键使用")

    g = p.add_argument_group("天气")
    g.add_argument("--weather", choices=config.WEATHER_TYPES, default=None)
    g.add_argument("--cloud", type=float)
    g.add_argument("--precip", type=float)
    g.add_argument("--visibility", type=float)
    g.add_argument("--humidity", type=float)

    g = p.add_argument_group("输出规格（AI 模式）")
    g.add_argument("-r", "--resolution", choices=config.SIZE_TIERS)
    g.add_argument("-a", "--aspect", choices=config.ASPECT_RATIOS)

    g = p.add_argument_group("渲染")
    g.add_argument("--light-level", type=int, choices=range(0, 13))
    g.add_argument("--wall-desc")
    g.add_argument("--ssaa", type=int, default=None)
    g.add_argument("--seed", type=int)

    g = p.add_argument_group("物理参数")
    g.add_argument("--cinnabar", nargs=3, type=float, metavar=("R", "G", "B"))
    g.add_argument("--noise-low", type=float)
    g.add_argument("--noise-mid", type=float)
    g.add_argument("--noise-high", type=float)
    g.add_argument("--diffusion", type=float)
    g.add_argument("--oxidation", type=float)
    g.add_argument("--shadow-strength", type=float)
    g.add_argument("--material-coupling", type=float,
                   help="字形随材质起伏的耦合强度（0=关闭）")
    g.add_argument("--exposure", type=float, help="画面曝光倍率")
    g.add_argument("--saturation", type=float, help="画面饱和度倍率")

    g = p.add_argument_group("控制")
    g.add_argument("--token")
    g.add_argument("--settings", action="store_true")
    g.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    g.add_argument("-y", "--yes", action="store_true")
    g.add_argument("-v", "--verbose", action="store_true")
    g.add_argument("--log-level",
                   choices=["DEBUG", "INFO", "WARN", "ERROR"])
    g.add_argument("--log-file", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--no-render", action="store_true")

    g = p.add_argument_group("查询")
    g.add_argument("--list-fonts", action="store_true")
    g.add_argument("--list-backgrounds", action="store_true")
    g.add_argument("--list-ntp", action="store_true")
    g.add_argument("--list-services", action="store_true")
    g.add_argument("--list-sizes", action="store_true")
    g.add_argument("--show-config", action="store_true")
    g.add_argument("--reset-config", action="store_true")
    g.add_argument("--version", action="version",
                   version=f"%(prog)s {config.VERSION}")
    return p


# ═══════════════════════════════════════════════════════════════════
def normalize_args(args):
    """--window-side → --window-orientation；--offline-bg → --background"""
    if args.window_orientation is None and args.window_side:
        args.window_orientation = args.window_side
    # 内置底图模式：--offline-bg 此前只切换了模式，并未参与选图（静默回退默认底图）
    if getattr(args, "offline_bg", None) and not args.background:
        args.background = args.offline_bg


def has_generate_args(args) -> bool:
    if args.text or args.input_image:
        return True
    if args.time or args.lat is not None or args.lon is not None:
        return True
    if args.light_level is not None:
        return True
    if args.resolution or args.aspect:
        return True
    if args.font or args.font_ratio is not None:
        return True
    if (args.font_anchor or args.font_pos_x is not None
            or args.font_pos_y is not None):
        return True
    if args.ssaa is not None or args.background:
        return True
    if args.window_orientation or args.window_scale is not None:
        return True
    if args.grid_rows is not None or args.grid_cols is not None:
        return True
    if args.grid_frame is not None or args.shadow_length is not None:
        return True
    if (args.weather or args.cloud is not None
            or args.precip is not None):
        return True
    if args.visibility is not None:
        return True
    if getattr(args, "humidity", None) is not None:
        return True
    if (getattr(args, "material_coupling", None) is not None
            or getattr(args, "exposure", None) is not None
            or getattr(args, "saturation", None) is not None):
        return True
    if args.no_ntp or args.no_gps or args.ntp_host or args.geo_service:
        return True
    if (getattr(args, "gps", False) or getattr(args, "ip_loc", False)
            or getattr(args, "set_location", None)):
        return True
    if args.wall_desc:
        return True
    return False


def detect_mode(args) -> str:
    if args.input_image:
        return "custom"
    if args.offline_bg:
        return "bg"
    if args.ai:
        return "ai"
    if has_generate_args(args):
        return "ai"
    return "menu"