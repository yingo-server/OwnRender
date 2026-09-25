#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — 工具

本文件专用。不 import 本框架其他文件。
可被本框架内任意小文件 import（retinex / patch / compose / text / pipeline）。

也可被其他框架拷贝一份（函数重复是允许的）。
"""
import math
import time
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter

import config


# ═══════════════════════════════════════════════════════════════════
# cv2 可选
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
# 数值
# ═══════════════════════════════════════════════════════════════════
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


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ═══════════════════════════════════════════════════════════════════
# 噪声
# ═══════════════════════════════════════════════════════════════════
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
    """分形噪声：多层 Perlin 叠加。"""
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
# 滤波
# ═══════════════════════════════════════════════════════════════════
def blur_2d(arr, radius):
    """高斯模糊。cv2 优先；大半径自动降采样（速度 ×100）。"""
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


def median_filter_2d(arr, size):
    """中值滤波（大窗口自动降采样）。"""
    size = max(3, int(size) | 1)
    h, w = arr.shape[:2]
    max_size = min(h, w) - 1
    if max_size < 3:
        return arr
    size = min(size, max_size) | 1

    if size > 31 and _HAS_CV2:
        scale = max(1, size // 15)
        sh = max(8, h // scale)
        sw = max(8, w // scale)
        small = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
        small_u8 = (np.clip(small, 0, 1) * 255).astype(np.uint8)
        small_size = max(3, min(size // scale, min(sh, sw) - 1) | 1)
        med = cv2.medianBlur(small_u8, small_size)
        med_f = med.astype(np.float32) / 255.0
        return cv2.resize(med_f, (w, h), interpolation=cv2.INTER_LINEAR)

    arr_u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    if _HAS_CV2:
        return cv2.medianBlur(arr_u8, size).astype(np.float32) / 255.0
    real_size = min(size, 9)
    pil = Image.fromarray(arr_u8, mode="L")
    return np.asarray(pil.filter(ImageFilter.MedianFilter(size=real_size)),
                      dtype=np.float32) / 255.0


# ═══════════════════════════════════════════════════════════════════
# 重采样
# ═══════════════════════════════════════════════════════════════════
def downsample_lanczos(img: Image.Image, tw: int, th: int) -> Image.Image:
    """缩小：INTER_AREA；放大：INTER_LANCZOS4。"""
    if img.size == (tw, th):
        return img
    if _HAS_CV2:
        arr = np.asarray(img)
        shrinking = (tw < img.width and th < img.height)
        interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
        out = cv2.resize(arr, (tw, th), interpolation=interp)
        if arr.ndim == 2:
            return Image.fromarray(out, mode="L")
        return Image.fromarray(out)
    return img.resize((tw, th), config.RESAMPLE_LANCZOS)


def resize_np(arr, tw, th):
    """numpy 数组缩放（cv2 优先）。"""
    if arr.shape[1] == tw and arr.shape[0] == th:
        return arr
    if _HAS_CV2:
        shrinking = tw < arr.shape[1] and th < arr.shape[0]
        interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
        return cv2.resize(arr, (tw, th), interpolation=interp)
    if arr.ndim == 2:
        pil = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8),
                              mode="L")
        pil = pil.resize((tw, th), config.RESAMPLE_LANCZOS)
        return np.asarray(pil, dtype=np.float32) / 255.0
    u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    pil = Image.fromarray(u8)
    pil = pil.resize((tw, th), config.RESAMPLE_LANCZOS)
    return np.asarray(pil, dtype=np.float32) / 255.0


# ═══════════════════════════════════════════════════════════════════
# 数组操作
# ═══════════════════════════════════════════════════════════════════
def shift_array_2d(arr, dx, dy):
    """任意方向数组偏移（dx>0 右，dy>0 下）。"""
    result = np.zeros_like(arr)
    H, W = arr.shape
    dx = int(dx); dy = int(dy)
    if dx == 0 and dy == 0:
        return arr.copy()
    if dx >= 0 and dy >= 0:
        if dy < H and dx < W: result[dy:, dx:] = arr[:H - dy, :W - dx]
    elif dx >= 0 and dy < 0:
        ady = -dy
        if ady < H and dx < W: result[:H - ady, dx:] = arr[ady:, :W - dx]
    elif dx < 0 and dy >= 0:
        adx = -dx
        if dy < H and adx < W: result[dy:, :W - adx] = arr[:H - dy, adx:]
    else:
        adx = -dx; ady = -dy
        if ady < H and adx < W: result[:H - ady, :W - adx] = arr[ady:, adx:]
    return result


# ═══════════════════════════════════════════════════════════════════
# 相机成像
# ═══════════════════════════════════════════════════════════════════
def aces_tonemap(x):
    """ACES filmic tone mapping（Narkowicz 近似）。保色温。"""
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    x = np.maximum(x, 0.0)
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)


def aces_tonemap_with_gain(x, gain=1.25):
    return aces_tonemap(x * gain)


# ═══════════════════════════════════════════════════════════════════
# 进度报告（若传入 progress 对象）
# ═══════════════════════════════════════════════════════════════════
def report(progress, p, msg=None):
    if progress is None:
        return
    progress.set_progress(p)
    if msg:
        progress.log(msg)