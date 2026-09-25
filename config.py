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
# 版本
# ═══════════════════════════════════════════════════════════════════
VERSION = "10.0.0"
PROG = "agnes-render"


# ═══════════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_DIR = BASE_DIR / "config"
CONFIG_SETTINGS = CONFIG_DIR / "settings.json"
CONFIG_PROMPTS  = CONFIG_DIR / "prompts.json"
CONFIG_LIGHTING = CONFIG_DIR / "lighting.json"
CONFIG_TOKEN    = CONFIG_DIR / "token.json"
CONFIG_LOCATION = CONFIG_DIR / "device_location.json"
LOG_DIR     = CONFIG_DIR / "logs"
OUTPUT_DIR  = BASE_DIR / "output"
FONT_DIR    = BASE_DIR / "fonts"
BG_DIR      = BASE_DIR / "background"


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

WINDOW_ORIENTATIONS = ["left", "right"]
WINDOW_ORIENTATION_ALIAS = {
    "w": "left", "west": "left", "n": "left", "nw": "left", "sw": "left",
    "e": "right", "east": "right", "s": "right", "ne": "right", "se": "right",
}
WINDOW_SIDE_AZ = {"left": 270, "right": 90}

WEATHER_TYPES = ["auto", "clear", "cloudy", "overcast", "rain", "snow", "haze"]
WEATHER_PRESETS = {
    "clear":    {"cloud": 0,  "vis": 20000, "humidity": 40, "precip": 0.0},
    "cloudy":   {"cloud": 50, "vis": 20000, "humidity": 55, "precip": 0.0},
    "overcast": {"cloud": 85, "vis": 15000, "humidity": 70, "precip": 0.0},
    "rain":     {"cloud": 80, "vis": 8000,  "humidity": 90, "precip": 2.0},
    "snow":     {"cloud": 85, "vis": 5000,  "humidity": 85, "precip": 3.0},
    "haze":     {"cloud": 40, "vis": 3000,  "humidity": 70, "precip": 0.0},
}
WEATHER_LABELS = {
    "auto": "自动（API 查询）", "clear": "晴", "cloudy": "多云",
    "overcast": "阴", "rain": "雨", "snow": "雪", "haze": "雾霾",
}

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
