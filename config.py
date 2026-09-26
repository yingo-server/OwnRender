#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agnes-render V35 配置层 + 全局常量 + 全局日志

职责：
  1. 全局常量（路径 / 尺寸 / 朝向 / 天气 / 锚点 / API URL）
  2. 出厂配置（settings / prompts / lighting / token）
  3. JSON 读写 + 缺失键自动补全
  4. 全局日志（LOG）

唯一横向共享点：所有 frame_*/ 都可以 import config
不依赖任何项目内其他模块。
"""
import os
import sys
import json
import time
import datetime
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

import numpy as np


# ═══════════════════════════════════════════════════════════════════
# 终端编码兼容层（最小必要：不改任何渲染 / 交互 / 布局逻辑）
#   ① 输出强制 UTF-8 + errors=replace —— 任何环境都不再因编码抛异常
#   ② Windows 控制台代码页切 65001 —— cmd / PowerShell 中文不再乱码
#   ③ locale 是 C/POSIX（终端多半不认框线）—— 框线符号降级为 ASCII，宽度 1:1 不错位
#   ④ C locale 下中文文件名 / 参数是"代理转义"字符 —— 打印前还原；
#      交给 Pillow 前也还原（Pillow 只接受能被 utf-8 编码的字符串）
# ═══════════════════════════════════════════════════════════════════
_ASCII_GLYPHS = (
    ("─", "-"), ("═", "="), ("│", "|"), ("━", "-"),
    ("┌", "+"), ("┐", "+"), ("└", "+"), ("┘", "+"),
    ("├", "+"), ("┤", "+"), ("┬", "+"), ("┴", "+"), ("┼", "+"),
    ("◆", "*"), ("▸", ">"), ("·", "-"), ("…", "~"),
    ("✓", "v"), ("✔", "v"), ("✗", "x"), ("✘", "x"),
    ("█", "#"), ("▒", ":"), ("░", "."), ("→", "->"), ("←", "<-"),
)

_STDIO_DONE = False
_TERM_UNICODE = True


def _decode_escapes(text):
    """把代理转义（surrogateescape）字符串还原成真正的 UTF-8 文本。"""
    if not isinstance(text, str) or not text:
        return text
    for ch in text:
        if "\udc80" <= ch <= "\udcff":
            break
    else:
        return text                      # 不含代理转义，原样返回
    for enc in (sys.getfilesystemencoding(), "ascii", "utf-8"):
        try:
            return text.encode(enc, "surrogateescape").decode("utf-8", "replace")
        except Exception:
            continue
    return text


def _fix_path_arg(obj):
    """路径参数（str / Path）统一还原成可被 utf-8 编码的字符串。"""
    if isinstance(obj, str):
        return _decode_escapes(obj)
    if isinstance(obj, os.PathLike):
        try:
            return _decode_escapes(os.fspath(obj))
        except Exception:
            return obj
    return obj


def _locale_tag():
    """按 POSIX 优先级取生效的 locale（LC_ALL > LC_CTYPE > LANG > LANGUAGE）。"""
    for k in ("LC_ALL", "LC_CTYPE", "LANG"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v.lower()
    return (os.environ.get("LANGUAGE") or "").strip().lower()


class _EncStream:
    """stdout / stderr 包装：还原代理转义 +（哑终端里）降级框线符号。"""

    def __init__(self, stream, degrade: bool):
        self._s = stream
        self._degrade = bool(degrade)

    def write(self, text):
        if isinstance(text, str) and text:
            text = _decode_escapes(text)
            if self._degrade:
                for a, b in _ASCII_GLYPHS:
                    if a in text:
                        text = text.replace(a, b)
        return self._s.write(text)

    def flush(self):
        return self._s.flush()

    def writable(self):
        return True

    def __getattr__(self, name):         # isatty / fileno / buffer / encoding …
        return getattr(self._s, name)


def _win_console_utf8():
    """Windows：控制台代码页切 UTF-8(65001)，否则 UTF-8 字节被当 GBK 解 = 乱码。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        if not k.GetConsoleOutputCP():    # 0 = 输出被重定向，不动系统状态
            return False
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
        return True
    except Exception:
        return False


def _patch_pillow_encoding():
    """Pillow 拿到代理转义字符串会在内部 encode('utf-8') 时崩掉（中文文件名 / 文本）。

    只在 Pillow 入口还原"传参副本"，不改引擎持有的原字符串，
    因此不影响任何文件系统语义（os.path / open 依旧按原样工作）。
    """
    try:
        from PIL import ImageFont
    except Exception:
        return
    try:
        _init = ImageFont.FreeTypeFont.__init__

        def _init2(self, font=None, *a, **kw):
            return _init(self, _fix_path_arg(font), *a, **kw)

        ImageFont.FreeTypeFont.__init__ = _init2
    except Exception:
        pass
    for meth in ("getmask", "getmask2", "getbbox", "getlength", "getsize"):
        try:
            orig = getattr(ImageFont.FreeTypeFont, meth, None)
            if orig is None or getattr(orig, "_enc_wrapped", False):
                continue

            def _wrap(fn):
                def wrapped(self, text, *a, **kw):
                    return fn(self, _decode_escapes(text), *a, **kw)
                wrapped._enc_wrapped = True
                return wrapped

            setattr(ImageFont.FreeTypeFont, meth, _wrap(orig))
        except Exception:
            continue


def ensure_utf8_stdio():
    """强制 UTF-8 输出；返回终端是否认 Unicode 框线符号。幂等，可重复调用。"""
    global _STDIO_DONE, _TERM_UNICODE
    if _STDIO_DONE:
        return _TERM_UNICODE
    _STDIO_DONE = True

    # ① 输出一律 UTF-8 + errors=replace：任何字符都不会再抛 UnicodeEncodeError
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None:
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # ② Windows 控制台切 65001（与强制 UTF-8 配套，cmd / PowerShell 才不乱码）
    win = _win_console_utf8()

    # ③ 终端认不认框线符号
    tag = _locale_tag()
    if os.environ.get("OWNRENDER_ASCII"):
        _TERM_UNICODE = False
    elif os.environ.get("OWNRENDER_UNICODE"):
        _TERM_UNICODE = True
    elif win:
        _TERM_UNICODE = True              # 控制台已按 UTF-8 工作
    elif not tag:
        _TERM_UNICODE = True              # locale 未设置：按现代终端处理
    elif "utf-8" in tag or "utf8" in tag:
        _TERM_UNICODE = True
    elif tag in ("c", "posix") or tag.startswith("c."):
        _TERM_UNICODE = False             # 明确的 C/POSIX：降级成 ASCII
    else:
        _TERM_UNICODE = True

    # ④ 文件系统编码不是 UTF-8（C locale）时：修输出 + 修 Pillow 入口的转义
    try:
        fs_utf8 = (sys.getfilesystemencoding() or "").lower() in ("utf-8", "utf8")
    except Exception:
        fs_utf8 = False
    if not fs_utf8 or not _TERM_UNICODE:
        for name in ("stdout", "stderr"):
            s = getattr(sys, name, None)
            if s is None or isinstance(s, _EncStream):
                continue
            try:
                setattr(sys, name, _EncStream(s, not _TERM_UNICODE))
            except Exception:
                pass
    if not fs_utf8:
        _patch_pillow_encoding()
    return _TERM_UNICODE


# ═══════════════════════════════════════════════════════════════════
# 版本
# ═══════════════════════════════════════════════════════════════════
VERSION = "10.0.0"
PROG = "agnes-render"


# ═══════════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════════
def _is_frozen() -> bool:
    """是否为打包后的可执行文件（Nuitka / PyInstaller）。"""
    return bool(getattr(sys, "frozen", False)) or ("__compiled__" in globals())


def _self_dir() -> Path:
    """本模块所在目录。打包后 onefile 指向解包临时目录，standalone 指向 dist 目录。"""
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd()


def _exe_dir():
    """可执行文件所在目录（打包后用户放自己素材的地方）。"""
    try:
        cand = Path(sys.argv[0]).resolve().parent
    except Exception:
        return None
    return cand if cand.is_dir() else None


def _writable(path: Path) -> bool:
    """目录是否可写（会尝试创建）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _resolve_base_dir() -> Path:
    """
    便携根目录：
      1) 环境变量 OWNRENDER_HOME
      2) 打包后：可执行文件同级目录（若含 background/fonts/config/output 之一）
      3) 源码目录
    """
    env = os.environ.get("OWNRENDER_HOME")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    src = _self_dir()
    exe = _exe_dir()
    if exe and exe.resolve() != src:
        for marker in ("background", "fonts", "config", "output"):
            if (exe / marker).exists():
                return exe
    return src


def _resolve_asset_dir(name: str, base: Path) -> Path:
    """素材目录：优先便携根目录（用户可替换），其次内置（打包时随包携带）。"""
    for cand in (base / name, _self_dir() / name):
        if cand.is_dir():
            return cand
    return base / name


# ── 路径 ────────────────────────────────────────────────────────────
BASE_DIR = _resolve_base_dir()

_DEF_CONFIG = BASE_DIR / "config"
if not _writable(_DEF_CONFIG):                      # 只读安装目录 → 退回用户配置目录
    _DEF_CONFIG = (Path(os.environ.get("XDG_CONFIG_HOME")
                        or (Path.home() / ".config")) / "ownrender")
CONFIG_DIR = _DEF_CONFIG
CONFIG_SETTINGS = CONFIG_DIR / "settings.json"
CONFIG_PROMPTS  = CONFIG_DIR / "prompts.json"
CONFIG_LIGHTING = CONFIG_DIR / "lighting.json"
CONFIG_TOKEN    = CONFIG_DIR / "token.json"
CONFIG_LOCATION = CONFIG_DIR / "device_location.json"
LOG_DIR     = CONFIG_DIR / "logs"

_DEF_OUTPUT = BASE_DIR / "output"
if not _writable(_DEF_OUTPUT):                      # 只读 → 退回用户主目录
    _DEF_OUTPUT = Path.home() / "OwnRender-output"
OUTPUT_DIR = _DEF_OUTPUT

FONT_DIR = _resolve_asset_dir("fonts", BASE_DIR)
BG_DIR   = _resolve_asset_dir("background", BASE_DIR)


# ═══════════════════════════════════════════════════════════════════
# 通用常量
# ═══════════════════════════════════════════════════════════════════
SIZE_TIERS = ["1K", "2K", "3K", "4K"]
ASPECT_RATIOS = ["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"]
SIZE_MAP = {
    ("1K","16:9"):"1024x576",("2K","16:9"):"2048x1152",
    ("3K","16:9"):"3072x1728",("4K","16:9"):"4096x2304",
    ("1K","9:16"):"576x1024",("2K","9:16"):"1152x2048",
    ("3K","9:16"):"1728x3072",("4K","9:16"):"2304x4096",
    ("1K","1:1"):"1024x1024",("2K","1:1"):"2048x2048",
    ("3K","1:1"):"3072x3072",("4K","1:1"):"4096x4096",
    ("1K","4:3"):"1024x768",("2K","4:3"):"2048x1536",
    ("3K","4:3"):"3072x2304",("4K","4:3"):"4096x3072",
    ("1K","3:4"):"768x1024",("2K","3:4"):"1536x2048",
    ("3K","3:4"):"2304x3072",("4K","3:4"):"3072x4096",
    ("1K","2:3"):"832x1248",("2K","2:3"):"1664x2496",
    ("3K","2:3"):"2496x3744",("4K","2:3"):"3328x4992",
    ("1K","3:2"):"1248x832",("2K","3:2"):"2496x1664",
    ("3K","3:2"):"3744x2496",("4K","3:2"):"4992x3328",
    ("1K","21:9"):"1344x576",("2K","21:9"):"2688x1152",
    ("3K","21:9"):"4032x1728",("4K","21:9"):"5376x2304",
}

# 窗户朝向：left/right 为历史写法（左=朝西 270°，右=朝东 90°），
# 另外支持真实罗盘 n/ne/e/se/s/sw/w/nw（正北 0°，顺时针）。
WINDOW_ORIENTATIONS = ["left", "right",
                       "n", "ne", "e", "se", "s", "sw", "w", "nw"]
WINDOW_ORIENTATION_ALIAS = {
    # 英文全称 → 简写（简写本身已是合法朝向，必须原样透传，
    # 之前把 s 映射成 right(朝东)、n 映射成 left(朝西) 是错的）
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw",
    "southeast": "se", "southwest": "sw",
    "l": "left", "r": "right",
}
WINDOW_SIDE_AZ = {
    "left": 270, "right": 90,
    "n": 0, "ne": 45, "e": 90, "se": 135,
    "s": 180, "sw": 225, "w": 270, "nw": 315,
}

WEATHER_TYPES = ["auto", "clear", "cloudy", "overcast", "shower", "rain",
                 "thunder", "snow", "haze", "fog"]
WEATHER_PRESETS = {
    # 这里全部是**物理输入量**（不是"风格参数"）：
    #   cloud 云量% / vis 能见度m / humidity 湿度% / precip 降水mm·h⁻¹
    #   temp 气温℃（决定雨还是雪！旧版缺这一项，导致"雪天"被判成"雨天"）
    #   code WMO 天气码（用于复用同一套分类逻辑）
    "clear":    {"cloud": 0,  "vis": 20000, "humidity": 40, "precip": 0.0,
                 "temp": 25.0, "code": 0},
    "cloudy":   {"cloud": 50, "vis": 20000, "humidity": 55, "precip": 0.0,
                 "temp": 22.0, "code": 2},
    "overcast": {"cloud": 85, "vis": 15000, "humidity": 70, "precip": 0.0,
                 "temp": 18.0, "code": 3},
    # 阵雨：云在开开合合，太阳时不时露脸（不是"整体变暗"）
    "shower":   {"cloud": 70, "vis": 12000, "humidity": 85, "precip": 0.6,
                 "temp": 20.0, "code": 80},
    "rain":     {"cloud": 80, "vis": 8000,  "humidity": 90, "precip": 2.0,
                 "temp": 16.0, "code": 63},
    "thunder":  {"cloud": 92, "vis": 6000,  "humidity": 88, "precip": 3.5,
                 "temp": 24.0, "code": 95},
    # 雪：气温必须在 0℃ 以下，才可能触发"雪地反照率 0.8 + 地面反弹"
    "snow":     {"cloud": 85, "vis": 5000,  "humidity": 85, "precip": 3.0,
                 "temp": -3.0, "code": 73},
    "haze":     {"cloud": 40, "vis": 3000,  "humidity": 70, "precip": 0.0,
                 "temp": 15.0, "code": 45},
    "fog":      {"cloud": 60, "vis": 600,   "humidity": 96, "precip": 0.0,
                 "temp": 5.0,  "code": 45},
}
WEATHER_LABELS = {
    "auto": "自动（API 查询）", "clear": "晴", "cloudy": "多云",
    "overcast": "阴", "shower": "阵雨", "rain": "雨",
    "thunder": "雷阵雨", "snow": "雪", "haze": "雾霾", "fog": "雾",
}

# 注：天气的「光质」（硬度/湿面/地面反弹/空气光/对比/饱和/色偏）**不在这里**，
# 全部由 frame_light/atmosphere.py 从物理量推导（cloud/precip/temp/vis + 几何）。
# 这里只保留"场景预设"——即天气的物理输入量（云量/能见度/湿度/降水）。

ANCHORS = ["center", "tl", "tr", "bl", "br", "tc", "bc", "lc", "rc"]
DEFAULT_ANCHOR = "center"
DEFAULT_POS_X, DEFAULT_POS_Y = 50.0, 50.0
MAX_SSAA = 16

FONT_EXTENSIONS  = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# ─────────────────────────────────────────────────────────────
# 文字渲染 / 年代感参数（先物理仿真，再视觉妥协）
# ─────────────────────────────────────────────────────────────
# 朱砂颜料反射率（线性 RGB）：叠字处对底光的乘性反射
CINNABAR_REFLECTANCE = np.array([0.52, 0.055, 0.048], dtype=np.float32)
# 多层噪声振幅（年代感；越大越斑驳）
TEXT_NOISE_LOW_AMP  = 0.12
TEXT_NOISE_MID_AMP  = 0.10
TEXT_NOISE_HIGH_AMP = 0.06
# 多层噪声空间尺度（占画幅比例，形状越低频→块越大）
TEXT_NOISE_LOW_SCALE  = 0.060
TEXT_NOISE_MID_SCALE  = 0.015
TEXT_NOISE_HIGH_SCALE = 0.004
# 颜料扩散
DIFFUSION_AMP   = 0.20
DIFFUSION_RATIO = 0.0018  # 高斯模糊半径 = H * ratio

# 氧化颗粒
OXIDATION_DOTS = 0.00010  # 颗粒密度（个/像素）
OXIDATION_AMP  = 0.30
# 边缘侵蚀
EDGE_ERODE_RATIO = 0.0015  # 侵蚀迭代次数 = H * ratio
# 接触阴影
SHADOW_LEN_MIN    = 0.0005  # 最小偏移 = H * LEN_MIN
SHADOW_LEN_MAX    = 0.0030  # 最大偏移 = H * LEN_MAX
SHADOW_BLUR_RATIO = 0.0010  # 模糊半径 = H * ratio
SHADOW_STRENGTH   = 0.25    # 遮挡强度
# 材质耦合强度（0 = 关闭，贴近参考实现的纯年代感）
TEXT_MATERIAL_COUPLING = 0.0

# ── 运行时覆盖（None = 使用设置里的默认值）──
VISUAL_EXPOSURE = None      # 画面曝光倍率
VISUAL_SATURATION = None    # 画面饱和度倍率


def _defaults_or(key, fallback):
    """读设置默认值，读不到就返回 fallback。"""
    try:
        v = get_defaults().get(key, fallback)
        return fallback if v is None else v
    except Exception:
        return fallback


try:
    from PIL import Image as _PIL_Image
    RESAMPLE_LANCZOS  = _PIL_Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = _PIL_Image.Resampling.BILINEAR
except (ImportError, AttributeError):
    try:
        RESAMPLE_LANCZOS  = _PIL_Image.LANCZOS
        RESAMPLE_BILINEAR = _PIL_Image.BILINEAR
    except Exception:
        RESAMPLE_LANCZOS  = None
        RESAMPLE_BILINEAR = None

AGNES_API_URL   = "https://apihub.agnes-ai.com/v1/images/generations"
AGNES_MODEL     = "agnes-image-2.1-flash"
OPEN_METEO_URL  = "https://api.open-meteo.com/v1/forecast"
NTP_EPOCH_DELTA = 2208988800

NTP_SERVERS = [
    ("pool.ntp.org", "全球池"), ("time.google.com", "Google"),
    ("time.cloudflare.com", "Cloudflare"), ("time.apple.com", "Apple"),
    ("time.windows.com", "Microsoft"), ("ntp.aliyun.com", "阿里云"),
    ("cn.pool.ntp.org", "中国池"), ("ntp.tencent.com", "腾讯云"),
]

GEO_SERVICES = [
    ("ipinfo.io", "全球", "https://ipinfo.io/json",
     lambda d: ((None, None, d.get("city", ""), d.get("region", ""), d.get("country", ""))
                if "loc" not in d else (*map(float, d["loc"].split(",")),
                d.get("city", ""), d.get("region", ""), d.get("country", "")))),
    ("ip-api.com", "全球", "http://ip-api.com/json/?lang=zh-CN",
     lambda d: (d.get("lat"), d.get("lon"), d.get("city", ""),
                d.get("regionName", ""), d.get("country", ""))),
    ("ipapi.co", "全球", "https://ipapi.co/json/",
     lambda d: (d.get("latitude"), d.get("longitude"), d.get("city", ""),
                d.get("region", ""), d.get("country_name", ""))),
    ("ipwho.is", "全球", "https://ipwho.is/",
     lambda d: (d.get("latitude"), d.get("longitude"), d.get("city", ""),
                d.get("region", ""), d.get("country", ""))),
]


# ═══════════════════════════════════════════════════════════════════
# 全局日志
# ═══════════════════════════════════════════════════════════════════
class Logger:
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
    COLORS = {"DEBUG": "36", "INFO": "32", "WARN": "33", "ERROR": "31"}

    def __init__(self, level="INFO", log_file=None):
        self.level = self.LEVELS.get(level.upper(), 20)
        self.fh = None
        self._open(log_file)

    def _open(self, log_file):
        if self.fh:
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None
        if log_file:
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                self.fh = open(log_file, "a", encoding="utf-8")
                self._fh(f"--- 会话启动 {datetime.datetime.now()} ---")
            except Exception:
                self.fh = None

    def configure(self, level=None, log_file=None):
        if level is not None:
            self.level = self.LEVELS.get(level.upper(), self.level)
        if log_file is not None:
            self._open(log_file)

    def _fh(self, line):
        if self.fh:
            try:
                self.fh.write(line + "\n")
                self.fh.flush()
            except Exception:
                pass

    def _emit(self, name, msg):
        if self.LEVELS[name] < self.level:
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            print(f"  \033[{self.COLORS[name]}m[{name[0]}]\033[0m "
                  f"\033[2m{ts}\033[0m {msg}")
        except Exception:
            print(f"  [{name[0]}] {ts} {msg}")
        full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._fh(f"{full} [{name:5}] {msg}")

    def debug(self, m): self._emit("DEBUG", m)
    def info(self, m):  self._emit("INFO",  m)
    def warn(self, m):  self._emit("WARN",  m)
    def error(self, m): self._emit("ERROR", m)
    def section(self, m): self.debug(f"=== {m} ===")
    def param(self, k, v): self.debug(f"{k} = {v}")
    def timing(self, label, t0):
        self.debug(f"{label}: {time.time() - t0:.2f}s")

    def close(self):
        if self.fh:
            try:
                self._fh(f"--- 会话结束 {datetime.datetime.now()} ---")
                self.fh.close()
            except Exception:
                pass
            self.fh = None


LOG = Logger()


# ═══════════════════════════════════════════════════════════════════
# 出厂配置
# ═══════════════════════════════════════════════════════════════════
FACTORY_SETTINGS = {
    "resolution": "2K",
    "aspect": "16:9",
    "ssaa": 8,
    "font_ratio": 0.18,
    "font": "",
    "font_anchor": "center",
    "font_pos_x": 50.0,
    "font_pos_y": 50.0,
    "window_orientation": "right",
    "window_scale": 0.65,
    "grid_rows": 3,
    "grid_cols": 2,
    "grid_frame_ratio": 0.18,
    "shadow_length": "auto",
    "weather_override": "auto",
    "background": "",
    "keep_lit": False,
    "log_level": "INFO",
    "log_to_file": False,
    "ntp_host": "",
    "geo_service": "",
    "smart_wrap": True,
    "visual_exposure": 1.0,
    "visual_saturation": 1.0,
    "material_coupling": 0.0,
    "location_providers": [],
    "location_use_su": False,
}

FACTORY_PROMPTS = {
    "wall": ("老旧的微水泥墙面，带有柔和的颗粒纹理和淡淡的岁月痕迹，"
             "墙面整体干净平整，没有任何装饰和物件"),
    "scene_profiles": {
        "0":  "深夜，极暗环境，画面以暗调为主。",
        "1":  "深夜，昏暗环境，冷色调。",
        "2":  "凌晨，昏暗冷调。",
        "3":  "破晓，微弱晨光，整体偏暗。",
        "4":  "黎明，清冷的天光。",
        "5":  "清晨，淡金色的晨光。",
        "6":  "上午，明亮柔和的自然光。",
        "7":  "正午，明亮的白光。",
        "8":  "午后，温暖的金色阳光。",
        "9":  "傍晚，金色夕阳。",
        "10": "黄昏，深橙红色的暮光。",
        "11": "入夜，深蓝色的环境光。",
        "12": "深夜，极暗环境。",
    },
    "vision": {
        "16:9": "横向展开的电影感宽幅画面，中心对称构图，左右留白对称。",
        "9:16": "纵向延伸的极简构图，顶部和底部留白极大。",
        "1:1":  "极简正方形构图，四周留白均匀。",
        "4:3":  "经典横向构图，画面重心平稳。",
        "3:4":  "经典纵向构图，画面重心平稳。",
        "2:3":  "纵向延伸的电影感构图。",
        "3:2":  "横向舒展的电影感构图。",
        "21:9": "超宽幅电影感构图，左右留白极大。",
    },
    "style_suffix": ("现代极简主义，平面设计风格，电影级摄影质感，"
                     "极高清晰度，极简构图，克制的高级感。"),
    "no_window":        "画面中不出现窗户、窗框、窗格等实体结构，"
                        "只有窗格形状的几何光斑投射在墙面上。",
    "no_window_strong": "",
    "no_entities":      "画面中没有任何人物、生物、家具或建筑结构。",
    "window_light_hint":"墙面上有清晰的窗格形状光斑，是画面的视觉焦点。",
}

FACTORY_LIGHTING = {
    # ══════════════════════════════════════════════════════════
    # 3D 场景
    # ══════════════════════════════════════════════════════════
    "scene": {
        "room_w_m":          4.0,
        "room_h_m":          3.0,
        "room_d_m":          4.0,
        "window_side":       "right",
        "window_w_m":        1.2,
        "window_h_m":        1.5,
        "window_cy_m":       1.5,
        "window_cz_m":       1.5,
        # ★ 窗格
        "grid_rows":         3,
        "grid_cols":         2,
        "grid_frame_ratio":  0.10,
        # 相机
        "camera_pos_m":      [0.0, 1.5, 3.0],
        "camera_fov_deg":    60,
    },

    # ══════════════════════════════════════════════════════════
    # 环境光目标亮度
    # ══════════════════════════════════════════════════════════
    "ambient_target_sun_max":    0.45,
    "ambient_target_sun_min":    0.28,
    "ambient_target_twilight":   0.20,
    "ambient_target_moon":       0.17,
    "ambient_target_none":       0.15,
    "ambient_cloud_threshold":   50.0,
    "ambient_cloud_decay":       0.15,

    "ambient_color_moon":     [0.55, 0.68, 0.95],
    "ambient_color_twilight": [0.75, 0.60, 0.55],
    "ambient_color_city":     [0.60, 0.62, 0.80],
    "ambient_color_none":     [0.50, 0.55, 0.75],
    "ambient_color_sun_mix":  0.70,

    "sky_target_srgb":       0.25,
    "ground_target_srgb":    0.15,

    "direct_gain_base":          15.0,
    "direct_gain_time_sun":      1.00,
    "direct_gain_time_moon":     0.55,
    "direct_gain_time_twilight": 0.50,
    "direct_gain_vis_min":       0.25,
    "direct_gain_vis_amp":       0.75,
    "direct_gain_vis_pow":       0.55,

    # 光斑几何（保留，供旧 patch.py 使用）
    "patch_ssaa":              3,
    "grid_min_frame_px":       5.0,
    "window_aspect":           1.5,
    "stretch_min":             0.5,
    "stretch_max":             3.5,

    "glass_noise_low":         0.02,
    "glass_noise_mid":         0.01,
    "glass_noise_high":        0.005,
    "transmission_strength":   0.20,
    "patch_frame_scatter":     0.35,
    "patch_bloom_strength":    0.03,
    "bloom_radius_ratio":      0.010,
    "glass_smudge_count":      0,
    "glass_smudge_size":       0.006,
    "glass_water_streak_count":0,
    "glass_water_streak_opacity": 0.15,
    "glass_caustics_strength": 0.03,
    "dust_particle_count":     15,
    "dust_particle_size":      0.003,
    "dust_particle_opacity":   0.15,
    "aged_enabled":            True,
    "aged_erode":              0.001,
    "aged_noise":              0.04,
    "aged_dark_spots":         0.0003,

    "patch_bounce_strength":   0.12,
    "material_strength":       0.30,
    "cracks_strength":         0.50,
    "wall_bump_strength":      0.06,
    "halo_strength":           0.15,
    "fresnel_strength":        0.10,

    "aces_gain":               1.25,
    "vignette_strength":       0.15,
    "shadow_blue_tint":        0.06,
    "sensor_curve_strength":   0.05,

    # ── 天气/曝光的参数**不在这里** ──────────────────────────────
    # 物理常数与全局可调参数统一放在 frame_light/atmosphere.py
    # （全局手调参数共 5 个，其余全部由 cloud/precip/temp/vis + 几何推导）。


    "penumbra_max_ratio":      0.015,
    "penumbra_sigma_divisor":  1.5,

    "overcast_blur_mult":      3.0,
    "haze_blur_mult":          2.0,
    "rain_droplet_count":      15,
    "rain_droplet_length":     0.15,
    "rain_droplet_opacity":    0.40,
    "snow_flake_count":        40,
    "snow_flake_size":         0.008,

    "weather_profile": {
        "clear": {
            "noise_mult": 1.0, "transmission_mult": 1.0, "scatter_mult": 1.0,
            "bloom_mult": 1.0, "smudge_abs": 0, "water_abs": 0,
            "dust_mult": 1.0, "caustics_mult": 1.0, "aged_mult": 1.0,
            "kill_grid": False,
        },
        "cloudy": {
            "noise_mult": 2.0, "transmission_mult": 2.0, "scatter_mult": 1.5,
            "bloom_mult": 1.5, "smudge_abs": 15, "water_abs": 0,
            "dust_mult": 1.2, "caustics_mult": 1.0, "aged_mult": 1.2,
            "kill_grid": False,
        },
        "overcast": {
            "noise_mult": 3.0, "transmission_mult": 3.0, "scatter_mult": 1.0,
            "bloom_mult": 2.0, "smudge_abs": 30, "water_abs": 0,
            "dust_mult": 1.0, "caustics_mult": 0.8, "aged_mult": 1.0,
            "kill_grid": True,
        },
        "rain": {
            "noise_mult": 3.5, "transmission_mult": 2.0, "scatter_mult": 0.8,
            "bloom_mult": 3.0, "smudge_abs": 40, "water_abs": 20,
            "dust_mult": 0.3, "caustics_mult": 0.3, "aged_mult": 1.0,
            "kill_grid": True,
        },
        # 阵雨：雨一阵一阵，玻璃上有水痕但间隙能透光 → 不完全 kills 窗格
        "shower": {
            "noise_mult": 2.5, "transmission_mult": 2.0, "scatter_mult": 0.9,
            "bloom_mult": 2.5, "smudge_abs": 30, "water_abs": 12,
            "dust_mult": 0.5, "caustics_mult": 0.5, "aged_mult": 1.0,
            "kill_grid": False,
        },
        # 雷阵雨：云底黑、雨急，但云缝里会漏下硬光
        "thunder": {
            "noise_mult": 4.0, "transmission_mult": 1.5, "scatter_mult": 0.7,
            "bloom_mult": 3.5, "smudge_abs": 45, "water_abs": 25,
            "dust_mult": 0.3, "caustics_mult": 0.2, "aged_mult": 1.0,
            "kill_grid": False,
        },
        "fog": {
            "noise_mult": 3.0, "transmission_mult": 3.5, "scatter_mult": 0.6,
            "bloom_mult": 3.0, "smudge_abs": 35, "water_abs": 10,
            "dust_mult": 2.0, "caustics_mult": 0.2, "aged_mult": 1.0,
            "kill_grid": True,
        },
        "snow": {
            "noise_mult": 3.0, "transmission_mult": 1.5, "scatter_mult": 1.0,
            "bloom_mult": 2.5, "smudge_abs": 15, "water_abs": 0,
            "dust_mult": 1.5, "caustics_mult": 0.3, "aged_mult": 1.0,
            "kill_grid": True,
        },
        "haze": {
            "noise_mult": 2.5, "transmission_mult": 1.5, "scatter_mult": 0.8,
            "bloom_mult": 2.0, "smudge_abs": 25, "water_abs": 0,
            "dust_mult": 3.0, "caustics_mult": 0.5, "aged_mult": 1.0,
            "kill_grid": True,
        },
    },

    "moon_visual_boost":       1.0,
    "city_visual_boost":       1.0,
}


# ═══════════════════════════════════════════════════════════════════
# JSON I/O
# ═══════════════════════════════════════════════════════════════════
def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, overlay: dict):
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _check_missing_keys(user: dict, default: dict, path="") -> List[str]:
    missing = []
    for k, v in default.items():
        cur = f"{path}.{k}" if path else k
        if k not in user:
            missing.append(cur)
        elif isinstance(v, dict) and isinstance(user[k], dict):
            missing.extend(_check_missing_keys(user[k], v, cur))
    return missing


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        merged = json.loads(json.dumps(default))
        _deep_merge(merged, user)
        return merged
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def ensure_config_files(force: bool = False) -> Tuple[bool, List[str]]:
    """首次运行生成 config/，缺失键自动补全。"""
    ensure_utf8_stdio()          # 任何入口走到这里之前，输出就已安全
    created = False
    all_missing = []
    for path, default in [
        (CONFIG_SETTINGS, FACTORY_SETTINGS),
        (CONFIG_PROMPTS,  FACTORY_PROMPTS),
        (CONFIG_LIGHTING, FACTORY_LIGHTING),
        (CONFIG_TOKEN,    {"api_token": ""}),
    ]:
        if force or not path.exists():
            _write_json(path, default)
            created = True
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                missing = _check_missing_keys(user, default)
                if missing:
                    merged = json.loads(json.dumps(default))
                    _deep_merge(merged, user)
                    _write_json(path, merged)
                    all_missing.extend([f"{path.name}:{m}" for m in missing])
            except (json.JSONDecodeError, OSError):
                _write_json(path, default)
                created = True
    try:
        if CONFIG_TOKEN.exists():
            os.chmod(CONFIG_TOKEN, 0o600)
    except OSError:
        pass
    return created, all_missing


# ═══════════════════════════════════════════════════════════════════
# 读写接口
# ═══════════════════════════════════════════════════════════════════
def get_defaults() -> dict:
    return _read_json(CONFIG_SETTINGS, FACTORY_SETTINGS)


def get_prompts() -> dict:
    return _read_json(CONFIG_PROMPTS, FACTORY_PROMPTS)


def get_lighting() -> dict:
    return _read_json(CONFIG_LIGHTING, FACTORY_LIGHTING)


def get_token() -> dict:
    return _read_json(CONFIG_TOKEN, {"api_token": ""})


def resolve_token(cli_token=None) -> str:
    if cli_token:
        return cli_token
    env = os.environ.get("AGNES_API_TOKEN")
    if env:
        return env
    return get_token().get("api_token", "")


def save_settings(d: dict): _write_json(CONFIG_SETTINGS, d)
def save_prompts(d: dict):  _write_json(CONFIG_PROMPTS,  d)
def save_lighting(d: dict): _write_json(CONFIG_LIGHTING, d)


def save_token(d: dict):
    _write_json(CONFIG_TOKEN, d)
    try:
        os.chmod(CONFIG_TOKEN, 0o600)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────
# 文字辅助（供 frame_render.text 使用）
# ─────────────────────────────────────────────────────────────
def load_font(path, size):
    """加载字体，返回 PIL FreeType 字体对象。

    对齐参考实现：优先使用 RAQM 布局引擎（复杂字形/连字更准），
    并对 .ttc/.otc 字体集合指定 index=0。
    """
    from PIL import ImageFont
    size = max(1, int(size))
    p = Path(str(path))
    kwargs = {}
    if p.suffix.lower() in (".ttc", ".otc"):
        kwargs["index"] = 0
    try:
        if hasattr(ImageFont, "Layout"):
            kwargs["layout_engine"] = ImageFont.Layout.RAQM
        return ImageFont.truetype(str(p), size, **kwargs)
    except Exception:
        kwargs.pop("layout_engine", None)
        return ImageFont.truetype(str(p), size, **kwargs)


def smart_split_text(text):
    """智能断行：对齐参考实现 split_text_lines。

    规则：
      1. 半角逗号归一为全角「，」；
      2. 有「，」→ 按它断行，并把「，」保留在行尾（末行除外）；
      3. 无「，」→ 单行；显式换行仍按行拆。
    """
    text = "" if text is None else str(text)
    out = []
    for raw in text.split(chr(10)):
        norm = raw.replace(",", "，").strip()
        if norm == "":
            continue
        if "，" in norm:
            parts = [p for p in norm.split("，") if p]
            if not parts:
                out.append(norm)
            else:
                out.extend([p + "，" for p in parts[:-1]] + [parts[-1]])
        else:
            out.append(norm)
    return out or [""]
