#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 4 层光照向量

职责：
  1. ambient  — 基础环境光（室内反射）
  2. sky      — 天空散射（冷蓝，随时间变）
  3. ground   — 地面反射（暖，从窗户底）
  4. direct   — 直射光峰值（乘 mask 后使用）

不 import 本框架其他文件。
只 import config + utils（本框架）。
被 light.py 编排调用。
"""
import numpy as np

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 1. 基础环境光
# ═══════════════════════════════════════════════════════════════════
def _scene_ambient(light, weather, R_mean, cfg) -> np.ndarray:
    """室内反射环境光。RGB 线性。"""
    # 目标墙面 sRGB（时间决定）
    if light.source == "sun":
        sun_min = float(cfg.get("ambient_target_sun_min", 0.28))
        sun_max = float(cfg.get("ambient_target_sun_max", 0.45))
        alt_n = min(1.0, max(0.0, light.alt / 90.0))
        target_srgb = sun_min + (sun_max - sun_min) * alt_n
    elif light.source == "twilight":
        target_srgb = float(cfg.get("ambient_target_twilight", 0.20))
    elif light.source == "moon":
        target_srgb = float(cfg.get("ambient_target_moon", 0.17))
    elif light.source == "none":
        target_srgb = float(cfg.get("ambient_target_none", 0.15))
    else:
        target_srgb = 0.25

    # 云量衰减
    threshold = float(cfg.get("ambient_cloud_threshold", 50.0))
    decay = float(cfg.get("ambient_cloud_decay", 0.15))
    if weather.cloud > threshold:
        ratio = (weather.cloud - threshold) / max(100.0 - threshold, 1.0)
        target_srgb *= (1.0 - decay * ratio)

    # sRGB → 线性 → 缩放（保留色调但让 I_new 均值 ≈ target）
    target_linear = float(utils.srgb_to_linear(
        np.array([target_srgb], dtype=np.float32))[0])
    scale = target_linear / max(float(R_mean), 0.001)

    # 色调
    if light.source == "moon":
        color = np.array(cfg.get("ambient_color_moon",
                                  [0.55, 0.68, 0.95]), dtype=np.float32)
    elif light.source == "twilight":
        color = np.array(cfg.get("ambient_color_twilight",
                                  [0.75, 0.60, 0.55]), dtype=np.float32)
    elif light.source == "city":
        color = np.array(cfg.get("ambient_color_city",
                                  [0.60, 0.62, 0.80]), dtype=np.float32)
    elif light.source == "none":
        color = np.array(cfg.get("ambient_color_none",
                                  [0.50, 0.55, 0.75]), dtype=np.float32)
    else:  # sun
        mix = float(cfg.get("ambient_color_sun_mix", 0.70))
        sun_col = light.color / max(float(light.color.max()), 1e-6)
        color = mix * sun_col + (1.0 - mix) * np.ones(3, dtype=np.float32)

    color = color / max(float(color.mean()), 1e-6)
    return color * scale


# ═══════════════════════════════════════════════════════════════════
# 2. 天空散射
# ═══════════════════════════════════════════════════════════════════
def _scene_sky_light(light, weather, R_mean, cfg) -> np.ndarray:
    """天空散射光。冷蓝，随时间变。"""
    if light.source == "sun":
        if light.alt >= 60:
            sky_rgb = [0.55, 0.70, 1.00]; sky_ratio = 0.25
        elif light.alt >= 30:
            sky_rgb = [0.60, 0.72, 0.95]; sky_ratio = 0.35
        elif light.alt >= 10:
            sky_rgb = [0.75, 0.70, 0.85]; sky_ratio = 0.45
        else:
            sky_rgb = [1.00, 0.65, 0.40]; sky_ratio = 0.60
    elif light.source == "twilight":
        sky_rgb = [0.70, 0.50, 0.60]; sky_ratio = 0.80
    elif light.source == "moon":
        sky_rgb = [0.40, 0.55, 1.00]; sky_ratio = 0.40
    else:
        sky_rgb = [0.50, 0.55, 0.75]; sky_ratio = 0.20

    # 云量：阴天全天空散射
    if weather.cloud > 30:
        cf = (weather.cloud - 30) / 70.0
        sky_ratio = sky_ratio * (1.0 - cf) + 1.0 * cf
        if weather.cloud > 60:
            gray = (weather.cloud - 60) / 40.0
            sky_rgb = [sky_rgb[i] * (1 - gray) + [0.70, 0.75, 0.85][i] * gray
                       for i in range(3)]

    sky_target_srgb = float(cfg.get("sky_target_srgb", 0.25)) * sky_ratio
    sky_linear = float(utils.srgb_to_linear(
        np.array([sky_target_srgb], dtype=np.float32))[0])
    color = np.array(sky_rgb, dtype=np.float32)
    color = color / max(float(color.mean()), 1e-6)
    scale = sky_linear / max(float(R_mean), 0.001)
    return color * scale


# ═══════════════════════════════════════════════════════════════════
# 3. 地面反射
# ═══════════════════════════════════════════════════════════════════
def _scene_ground_bounce(light, weather, R_mean, cfg) -> np.ndarray:
    """地面反射光。暖色，从窗户底部斜射。"""
    if light.source not in ("sun", "twilight"):
        return np.zeros(3, dtype=np.float32)

    ground_rgb = [1.00, 0.85, 0.65]
    ground_ratio = 0.15 if light.source == "sun" else 0.25

    if weather.cloud > 50:
        ground_ratio *= (1.0 - (weather.cloud - 50) / 100.0)

    ground_target_srgb = (float(cfg.get("ground_target_srgb", 0.15)) *
                          ground_ratio)
    ground_linear = float(utils.srgb_to_linear(
        np.array([ground_target_srgb], dtype=np.float32))[0])
    color = np.array(ground_rgb, dtype=np.float32)
    color = color / max(float(color.mean()), 1e-6)
    scale = ground_linear / max(float(R_mean), 0.001)
    return color * scale


# ═══════════════════════════════════════════════════════════════════
# 4. 直射光增益
# ═══════════════════════════════════════════════════════════════════
def _scene_direct_gain(light, cfg) -> float:
    """直射光视觉增益（峰值 ~15）。"""
    irr = light.irradiance
    if irr < 0.0005:
        return 0.0
    base = float(cfg.get("direct_gain_base", 15.0))
    vis_min = float(cfg.get("direct_gain_vis_min", 0.25))
    vis_amp = float(cfg.get("direct_gain_vis_amp", 0.75))
    vis_pow = float(cfg.get("direct_gain_vis_pow", 0.55))

    if light.source == "moon":
        time_factor = float(cfg.get("direct_gain_time_moon", 0.55))
    elif light.source == "twilight":
        time_factor = float(cfg.get("direct_gain_time_twilight", 0.50))
    else:
        time_factor = float(cfg.get("direct_gain_time_sun", 1.00))

    vis = vis_min + vis_amp * min(1.0, irr ** vis_pow)
    return vis * base * time_factor


# ═══════════════════════════════════════════════════════════════════
# 对外：4 层光照向量
# ═══════════════════════════════════════════════════════════════════
def compute_scene_lights(light, weather, R_mean, cfg=None) -> dict:
    """
    返回 4 层光照向量（RGB 线性）：
      ambient — 室内环境
      sky     — 天空散射
      ground  — 地面反射
      direct  — 直射峰值（未乘 mask）
    """
    if cfg is None:
        cfg = config.get_lighting()

    ambient = _scene_ambient(light, weather, R_mean, cfg)
    sky = _scene_sky_light(light, weather, R_mean, cfg)
    ground = _scene_ground_bounce(light, weather, R_mean, cfg)

    if light.source == "none" or light.irradiance < 0.0005:
        direct = np.zeros(3, dtype=np.float32)
    else:
        color_lin = utils.srgb_to_linear(np.clip(light.color, 0, 1))
        gain = _scene_direct_gain(light, cfg)
        direct = color_lin * gain

    config.LOG.param("L_ambient", f"{ambient.tolist()}")
    config.LOG.param("L_sky",     f"{sky.tolist()}")
    config.LOG.param("L_ground",  f"{ground.tolist()}")
    config.LOG.param("L_direct",  f"{direct.tolist()}")

    return {
        "ambient": ambient,
        "sky": sky,
        "ground": ground,
        "direct": direct,
    }