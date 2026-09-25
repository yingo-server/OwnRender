#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — 主合成 + 相机效果

职责：
  1. ACES tone mapping（保色温）
  2. 5 层光照合成：I_amb + I_dir
  3. 光斑反弹光（周围暖晕）
  4. 潮湿镜面反光
  5. 材质影响合成
  6. 阴影色偏
  7. 镜头渐晕
  8. CMOS 响应曲线

不 import 本框架其他文件。
只 import config + utils（本框架）。
被 pipeline.py 编排调用。
"""
import time
from typing import Dict, Optional

import numpy as np
from PIL import Image

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 光斑反弹光
# ═══════════════════════════════════════════════════════════════════
def _apply_patch_bounce(I_out, patch_mask, L_patch_total, W, H, cfg,
                         bounce_strength=0.12):
    """光斑反弹光：光斑周围暖晕。"""
    if bounce_strength <= 0:
        return I_out
    rho_wall = 0.5
    bounce_source = patch_mask * L_patch_total * rho_wall
    radius_small = max(3.0, min(W, H) * 0.03)
    radius_large = max(8.0, min(W, H) * 0.08)
    bounce_small = utils.blur_2d(bounce_source, radius_small)
    bounce_large = utils.blur_2d(bounce_source, radius_large)
    bounce = bounce_small * 0.6 + bounce_large * 0.4
    bounce_rgb = (bounce[..., None]
                  * np.array([1.0, 0.92, 0.80], dtype=np.float32)[None, None, :])
    return I_out + bounce_rgb * bounce_strength


# ═══════════════════════════════════════════════════════════════════
# 相机效果
# ═══════════════════════════════════════════════════════════════════
def _apply_vignetting(I_out, W, H, strength=0.15):
    if strength <= 0:
        return I_out
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = W / 2.0, H / 2.0
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_dist
    vignette = 1.0 - strength * dist ** 2
    return I_out * vignette[..., None]


def _apply_shadow_tint(I_out, shadow_blue=0.06):
    if shadow_blue <= 0:
        return I_out
    lum = I_out.mean(axis=2, keepdims=True)
    weight = np.clip(1.0 - lum * 2.0, 0, 1)
    blue_tint = np.array([0.0, 0.05, 0.10], dtype=np.float32)
    tint = weight * blue_tint[None, None, :] * shadow_blue
    return I_out + tint


def _apply_sensor_curve(I_out, strength=0.05):
    if strength <= 0:
        return I_out
    return I_out * (1.0 + strength * (1.0 - np.clip(I_out, 0, 1)))


# ═══════════════════════════════════════════════════════════════════
# 主合成
# ═══════════════════════════════════════════════════════════════════
def synthesize(R_clean: np.ndarray,
               patch_mask: np.ndarray,
               scene_lights: Dict[str, np.ndarray],
               light,
               weather,
               material_map: Optional[np.ndarray] = None,
               cfg: Optional[dict] = None,
               progress=None) -> np.ndarray:
    """
    5 层光照合成 → 线性 RGB 输出（float32, 0~1）。

    输入：
      R_clean      (H, W, 3) 反射率
      patch_mask   (H, W)    光斑形状（0~1）
      scene_lights dict      ambient / sky / ground / direct
      light        LightResult
      weather      WeatherInfo
      material_map (H, W)    材质图（可选）

    输出：
      I_out        (H, W, 3) 线性 RGB
    """
    if cfg is None:
        cfg = config.get_lighting()
    rep = utils.report

    H, W = R_clean.shape[:2]

    L_ambient = scene_lights["ambient"]
    L_sky = scene_lights["sky"]
    L_ground = scene_lights["ground"]
    L_direct = scene_lights["direct"]

    # 环境光 3 层相加
    L_env_total = L_ambient + L_sky + L_ground
    I_amb = R_clean * L_env_total[None, None, :]

    # 直射光
    if light.source == "none" or light.irradiance < 0.0005:
        I_out = I_amb
        rep(progress, 0.30, "仅环境光")
    else:
        I_dir_raw = R_clean * (patch_mask[..., None] * L_direct[None, None, :])
        aces_gain = float(cfg.get("aces_gain", 1.25))
        I_dir = utils.aces_tonemap_with_gain(I_dir_raw, gain=aces_gain)

        config.LOG.param("I_dir_raw_max", f"{float(I_dir_raw.max()):.3f}")
        config.LOG.param("I_dir_tm_max",  f"{float(I_dir.max()):.3f}")

        I_out = I_amb + I_dir
        rep(progress, 0.50, "直射 + ACES")

        # 光斑反弹光
        bounce = float(cfg.get("patch_bounce_strength", 0.12))
        if bounce > 0:
            rep(progress, 0.55, "光斑反弹光")
            L_patch_total = I_dir.mean(axis=2)
            I_out = _apply_patch_bounce(I_out, patch_mask, L_patch_total,
                                          W, H, cfg, bounce_strength=bounce)

    # 潮湿镜面反光
    wetness = max(0.0, min(1.0, weather.humidity / 100.0))
    if wetness > 0.3 and patch_mask.max() > 0.01:
        specular = (patch_mask[..., None]
                    * L_env_total[None, None, :] * 2.0 * wetness)
        I_out = I_out + specular * 0.15
        rep(progress, 0.62, "潮湿反光")

    # 材质影响合成
    mat_strength = float(cfg.get("material_strength", 0.3))
    if material_map is not None and mat_strength > 0:
        rep(progress, 0.70, "材质影响")
        mat_factor = 1.0 + (material_map - 1.0) * mat_strength
        I_out = I_out * mat_factor[..., None]

    # 阴影色偏（暗部偏蓝）
    shadow_blue = float(cfg.get("shadow_blue_tint", 0.06))
    I_out = _apply_shadow_tint(I_out, shadow_blue)

    # 曝光 / 饱和度（用户微调）
    defaults = config.get_defaults()
    exposure = float(defaults.get("visual_exposure", 1.0))
    if exposure != 1.0:
        I_out = I_out * exposure
    saturation = float(defaults.get("visual_saturation", 1.0))
    if saturation != 1.0:
        gray = I_out.mean(axis=2, keepdims=True)
        I_out = gray + (I_out - gray) * saturation

    # 镜头渐晕
    vig = float(cfg.get("vignette_strength", 0.15))
    if vig > 0:
        rep(progress, 0.80, "镜头渐晕")
        I_out = _apply_vignetting(I_out, W, H, vig)

    # CMOS 响应曲线
    sensor = float(cfg.get("sensor_curve_strength", 0.05))
    if sensor > 0:
        rep(progress, 0.85, "CMOS 响应")
        I_out = _apply_sensor_curve(I_out, sensor)

    np.clip(I_out, 0.0, 1.0, out=I_out)
    config.LOG.param("I_out_max", f"{float(I_out.max()):.3f}")
    rep(progress, 0.90, "合成完成")

    return I_out


# ═══════════════════════════════════════════════════════════════════
# 编码为 PIL 图像
# ═══════════════════════════════════════════════════════════════════
def encode_srgb(I_out_linear: np.ndarray) -> Image.Image:
    """线性 RGB → sRGB → PIL Image。"""
    lit_srgb = utils.linear_to_srgb(I_out_linear)
    lit_u8 = (lit_srgb * 255).astype(np.uint8)
    return Image.fromarray(lit_u8)