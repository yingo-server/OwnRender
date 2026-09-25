#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — Retinex 分解 + 材质分析

职责：
  1. 多尺度 Retinex 分解 I = R × S（工作尺寸 ≤1024）
  2. 异常检测（光斑/阴影 inpaint）
  3. 材质图提取（反射率偏差）
  4. 裂纹内渗（材质耦合）

不 import 本框架其他文件。
只 import config + utils（本框架）。
被 pipeline.py 编排调用。
"""
from typing import Tuple, Dict

import numpy as np

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 内部：inpaint
# ═══════════════════════════════════════════════════════════════════
def _inpaint_regions(arr, mask, blur_size=21):
    """用中值滤波填充 mask 区域（逐通道）。"""
    if not mask.any():
        return arr
    result = arr.copy()
    for c in range(arr.shape[2]):
        ch = arr[..., c]
        ch_med = utils.median_filter_2d(ch, blur_size)
        result[..., c] = np.where(mask, ch_med, ch)
    return result


# ═══════════════════════════════════════════════════════════════════
# Retinex 分解
# ═══════════════════════════════════════════════════════════════════
def decompose_albedo(wall_lin: np.ndarray, cfg: dict,
                     progress=None) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """
    多尺度 Retinex 分解。

    学字体渲染 SSAA 思路：
      光照 S 是低频 → 1024 工作尺寸算
      R 除法在原始分辨率 → 保留纹理
      均值匹配 → 保留原亮度

    20+ 进度点。
    """
    rep = utils.report
    H, W = wall_lin.shape[:2]
    short_side = min(H, W)

    # ══════════ 阶段 0：缩放到工作尺寸 ══════════
    rep(progress, 0.005, f"输入 {W}x{H}")
    MAX_WORK = 1024
    if short_side > MAX_WORK:
        scale = MAX_WORK / short_side
        work_H = max(64, int(H * scale))
        work_W = max(64, int(W * scale))
        config.LOG.param("Retinex 缩放", f"{W}x{H} → {work_W}x{work_H}")
        rep(progress, 0.010)
        wall_work = utils.resize_np(wall_lin, work_W, work_H)
        rep(progress, 0.030, f"缩放 → {work_W}x{work_H}")
    else:
        work_W, work_H = W, H
        wall_work = wall_lin
        rep(progress, 0.030, f"工作尺寸 {work_W}x{work_H}")

    gray_work = (0.2126 * wall_work[..., 0] +
                 0.7152 * wall_work[..., 1] +
                 0.0722 * wall_work[..., 2])
    gray_work = np.clip(gray_work, 1e-6, None)
    rep(progress, 0.045, "灰度通道")

    # ══════════ 阶段 1：多尺度高斯 ══════════
    rep(progress, 0.055, "log(I)")
    log_gray = np.log(gray_work)
    rep(progress, 0.070)

    scales = [0.15, 0.35, 0.60]
    weights = [0.20, 0.30, 0.50]
    log_S = np.zeros_like(log_gray)

    for i, (s, w) in enumerate(zip(scales, weights)):
        radius = max(2.0, min(work_W, work_H) * s)
        base_p = 0.070 + i * 0.100
        rep(progress, base_p, f"高斯层 {i+1}/3 (σ={radius:.0f})")
        log_S += w * utils.blur_2d(log_gray, radius)
        rep(progress, base_p + 0.080)

    rep(progress, 0.380, "log(R) = log(I) - log(S)")
    log_R = log_gray - log_S
    S_work = np.exp(log_S)
    rep(progress, 0.400)

    # ══════════ 阶段 2：S 上采样回原尺寸 ══════════
    if work_W != W or work_H != H:
        rep(progress, 0.420, f"S 上采样 → {W}x{H}")
        S_gray = utils.resize_np(S_work, W, H)
        rep(progress, 0.470)
    else:
        S_gray = S_work
        rep(progress, 0.470)

    # ══════════ 阶段 3：原始分辨率 R = I / S ══════════
    rep(progress, 0.480, "R = I / S（原始分辨率）")
    S_safe = np.clip(S_gray, 1e-6, None)
    R = wall_lin / S_safe[..., None]
    rep(progress, 0.520)

    rep(progress, 0.540, "均值匹配")
    target_mean = float(wall_lin.mean())
    current_mean = float(R.mean())
    if current_mean > 1e-6:
        R = R * (target_mean / current_mean)
    R_clean = np.clip(R, 0.001, 1.0)
    rep(progress, 0.560, f"albedo_mean={float(R_clean.mean()):.4f}")

    # ══════════ 阶段 4：异常检测 ══════════
    rep(progress, 0.580, "异常检测: 中值基线")
    S_work_for_median = (utils.resize_np(S_gray, work_W, work_H)
                         if work_W != W or work_H != H else S_gray)
    median_size = max(11, int(min(work_W, work_H) * 0.05) | 1)
    config.LOG.param("中值窗口", f"{median_size} (工作尺寸)")

    rep(progress, 0.620, f"中值滤波 size={median_size}")
    S_baseline_work = utils.median_filter_2d(S_work_for_median, median_size)
    rep(progress, 0.680)

    S_baseline = (utils.resize_np(S_baseline_work, W, H)
                  if work_W != W or work_H != H else S_baseline_work)
    rep(progress, 0.700)

    deviation = S_gray - S_baseline
    bright_mask = deviation > 0.15
    dark_mask = deviation < -0.20
    bright_ratio = float(bright_mask.mean())
    dark_ratio = float(dark_mask.mean())
    rep(progress, 0.720,
        f"光斑 {bright_ratio*100:.2f}% 阴影 {dark_ratio*100:.2f}%")

    # ══════════ 阶段 5：inpaint ══════════
    need_inpaint = ((0 < bright_ratio < 0.30) or
                    (0 < dark_ratio < 0.30))

    if need_inpaint and (work_W != W or work_H != H):
        rep(progress, 0.740, "缩小 R + mask")
        R_work = utils.resize_np(R_clean, work_W, work_H)
        bright_work = utils.resize_np(bright_mask.astype(np.float32),
                                       work_W, work_H) > 0.5
        dark_work = utils.resize_np(dark_mask.astype(np.float32),
                                     work_W, work_H) > 0.5
        rep(progress, 0.780)

        if 0 < bright_ratio < 0.30:
            rep(progress, 0.800, "修复光斑")
            R_work = _inpaint_regions(R_work, bright_work,
                                       blur_size=median_size)
            rep(progress, 0.840)
        if 0 < dark_ratio < 0.30:
            rep(progress, 0.860, "修复阴影")
            R_work = _inpaint_regions(R_work, dark_work,
                                       blur_size=median_size)
            rep(progress, 0.890)

        rep(progress, 0.900, "R 上采样回原尺寸")
        R_clean = utils.resize_np(R_work, W, H)
        rep(progress, 0.920)
    else:
        if 0 < bright_ratio < 0.30:
            rep(progress, 0.800, "修复光斑")
            R_clean = _inpaint_regions(R_clean, bright_mask,
                                        blur_size=median_size)
            rep(progress, 0.840)
        if 0 < dark_ratio < 0.30:
            rep(progress, 0.860, "修复阴影")
            R_clean = _inpaint_regions(R_clean, dark_mask,
                                        blur_size=median_size)
            rep(progress, 0.890)
        rep(progress, 0.920)

    R_clean = np.clip(R_clean, 0.001, 1.0)

    # ══════════ 阶段 6：采样统计 ══════════
    rep(progress, 0.940, "采样统计")
    stats = {
        "albedo_mean": float(R_clean.mean()),
        "albedo_std":  float(R_clean.std()),
        "albedo_p50":  float(np.percentile(R_clean, 50)),
        "albedo_p90":  float(np.percentile(R_clean, 90)),
        "bright_ratio": bright_ratio,
        "dark_ratio": dark_ratio,
        "S_mean": float(S_gray.mean()),
        "S_std":  float(S_gray.std()),
        "work_size": f"{work_W}x{work_H}",
    }
    rep(progress, 1.000)
    return R_clean, S_gray, stats


# ═══════════════════════════════════════════════════════════════════
# 材质分析
# ═══════════════════════════════════════════════════════════════════
def analyze_wall_material(R_clean: np.ndarray, W: int, H: int,
                           cfg: dict) -> np.ndarray:
    """
    从 R_clean 提取材质图（均值 ≈ 1.0）：
      > 1.0 → 局部反射率高（凸起）
      < 1.0 → 局部反射率低（裂纹、凹坑）
    """
    lum = R_clean.mean(axis=2)
    large = utils.blur_2d(lum, max(10.0, min(W, H) * 0.05))
    large = np.maximum(large, 1e-6)
    variation = lum / large
    m = float(variation.mean())
    if m > 1e-6:
        variation = variation / m
    return np.clip(variation, 0.65, 1.45).astype(np.float32)


def apply_material_cracks(mask: np.ndarray, R_clean: np.ndarray,
                           cfg: dict, strength: float = 0.5) -> np.ndarray:
    """
    裂纹/凹坑 → 光线内渗（凹处变暗）。
    """
    if strength <= 0:
        return mask
    lum = R_clean.mean(axis=2)
    median = utils.median_filter_2d(lum, 5)
    cracks = np.clip(median - lum, 0, 1)
    cracks = np.clip(cracks * 3.0, 0, 1)
    return mask * (1.0 - cracks * strength)