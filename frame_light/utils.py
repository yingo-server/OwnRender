#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 工具

本文件专用。不 import 本框架其他文件。
可被本框架内任意小文件 import（astro / geometry / scene / light / scene3d / raytrace）。

函数可能与 frame_render/utils.py 重复。这是有意为之：
每个子框架有独立的工具，修改渲染工具不影响光照。
"""
import math
import datetime
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter

import config


# ═══════════════════════════════════════════════════════════════════
# cv2 可选（raytrace 的 blur_2d 会用到）
# ═══════════════════════════════════════════════════════════════════
try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False


# ═══════════════════════════════════════════════════════════════════
# 色彩空间
# ═══════════════════════════════════════════════════════════════════
def srgb_to_linear(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92,
                    np.power((x + 0.055) / 1.055, 2.4))


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92,
                    1.055 * np.power(x, 1.0 / 2.4) - 0.055)


# ═══════════════════════════════════════════════════════════════════
# 时间
# ═══════════════════════════════════════════════════════════════════
def to_utc_naive(dt: datetime.datetime) -> datetime.datetime:
    """任意 datetime → UTC naive。"""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def parse_time(s: str) -> datetime.datetime:
    """解析时间。优先 ISO 8601。"""
    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except ValueError:
        pass
    now = datetime.datetime.now()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%m-%d %H:%M", "%m-%d", "%H:%M"]:
        try:
            dt = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt: dt = dt.replace(year=now.year)
        if "%m" not in fmt: dt = dt.replace(month=now.month)
        if "%d" not in fmt: dt = dt.replace(day=now.day)
        return dt.astimezone()
    raise ValueError(f"无法解析时间: {s}")


# ═══════════════════════════════════════════════════════════════════
# 数值
# ═══════════════════════════════════════════════════════════════════
def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def stable_seed(*values) -> int:
    """FNV-1a 哈希，支持 str / int / float。"""
    h = 2166136261
    for v in values:
        if isinstance(v, str):
            x = 0
            for ch in v:
                x = (x * 31 + ord(ch)) & 0xFFFFFFFF
        else:
            try:
                x = int(abs(float(v)) * 1000) & 0xFFFFFFFF
            except (ValueError, TypeError):
                x = 0
        h ^= x
        h = (h * 16777619) & 0xFFFFFFFF
    return h & 0x7FFFFFFF


# ═══════════════════════════════════════════════════════════════════
# 方位词
# ═══════════════════════════════════════════════════════════════════
def az_to_h_word(az: float) -> str:
    s = math.sin(math.radians(az))
    if s > 0.15: return "偏左"
    if s < -0.15: return "偏右"
    return "居中"


def alt_to_v_word(alt: float) -> str:
    if alt > 55: return "偏上"
    if alt > 25: return "居中"
    return "偏下"


# ═══════════════════════════════════════════════════════════════════
# 进度报告
# ═══════════════════════════════════════════════════════════════════
def report(progress, p, msg=None):
    """统一进度报告。progress 为 None 时跳过。"""
    if progress is None:
        return
    progress.set_progress(p)
    if msg:
        progress.log(msg)


# ═══════════════════════════════════════════════════════════════════
# 图像工具
# ═══════════════════════════════════════════════════════════════════
def blur_2d(arr, radius):
    """高斯模糊。cv2 优先；大半径自动降采样。"""
    if radius < 0.5:
        return arr
    arr_u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)

    if _HAS_CV2 and radius > 100:
        h, w = arr.shape[:2]
        scale = max(1, int(radius / 50))
        sh = max(8, h // scale)
        sw = max(8, w // scale)
        small = cv2.resize(arr_u8, (sw, sh), interpolation=cv2.INTER_AREA)
        small_r = max(0.5, radius / scale)
        blurred = cv2.GaussianBlur(small, (0, 0), sigmaX=float(small_r))
        out = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_LINEAR)
        return out.astype(np.float32) / 255.0

    if _HAS_CV2 and radius >= 8:
        out = cv2.GaussianBlur(arr_u8, (0, 0), sigmaX=float(radius))
        return out.astype(np.float32) / 255.0

    pil = Image.fromarray(arr_u8, mode="L")
    pil = pil.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(pil, dtype=np.float32) / 255.0


def resize_np(arr, tw, th):
    """numpy 数组缩放（cv2 优先，PIL 回退）。"""
    if arr.shape[1] == tw and arr.shape[0] == th:
        return arr
    if _HAS_CV2:
        shrinking = tw < arr.shape[1] and th < arr.shape[0]
        interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
        return cv2.resize(arr, (tw, th), interpolation=interp)
    # PIL 回退
    if arr.ndim == 2:
        pil = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8),
                              mode="L")
        pil = pil.resize((tw, th), config.RESAMPLE_LANCZOS)
        return np.asarray(pil, dtype=np.float32) / 255.0
    u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    pil = Image.fromarray(u8)
    pil = pil.resize((tw, th), config.RESAMPLE_LANCZOS)
    return np.asarray(pil, dtype=np.float32) / 255.0


def perlin_noise(W, H, scale_ratio, rng):
    """低分辨率随机图 → 双线性放大。"""
    sw = max(2, int(W * scale_ratio))
    sh = max(2, int(H * scale_ratio))
    low = rng.random((sh, sw)).astype(np.float32)
    low_u8 = (low * 255).astype(np.uint8)
    if _HAS_CV2:
        out = cv2.resize(low_u8, (W, H), interpolation=cv2.INTER_LINEAR)
        return out.astype(np.float32) / 255.0
    img = Image.fromarray(low_u8, mode="L")
    img = img.resize((W, H), config.RESAMPLE_BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def fbm_noise(W, H, octaves, base_scale, rng):
    """分形噪声。"""
    out = np.zeros((H, W), dtype=np.float32)
    amp = 1.0
    total_amp = 0.0
    scale = base_scale
    for _ in range(octaves):
        out += perlin_noise(W, H, scale, rng) * amp
        total_amp += amp
        amp *= 0.5
        scale *= 2.0
    return out / max(total_amp, 1e-6)


# ═══════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════
def _self_test():
    """验证工具完整性。"""
    print("stable_seed =", stable_seed("a", 1.0, 2.5))

    arr = np.random.rand(64, 128).astype(np.float32)
    b = blur_2d(arr, 5.0)
    print(f"blur_2d shape={b.shape} range=[{b.min():.3f}, {b.max():.3f}]")

    r = resize_np(arr, 32, 64)
    print("resize_np shape:", r.shape)

    rng = np.random.default_rng(42)
    n = perlin_noise(64, 64, 0.1, rng)
    print("perlin_noise shape:", n.shape)

    f = fbm_noise(64, 64, 4, 0.05, rng)
    print("fbm_noise shape:", f.shape)

    print("_HAS_CV2 =", _HAS_CV2)
    print("OK")


if __name__ == "__main__":
    _self_test()