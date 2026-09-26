#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 光斑几何

职责：
  1. 光斑在屏幕上的位置（方位/高度 → cx/cy）
  2. 光斑大小（高度角 → 拉伸比）
  3. 半影宽度（光源角直径 + 天气）
  4. 阴影方向与长度

不 import 本框架其他文件。
只 import config + utils（本框架）。
被 light.py 编排调用。
"""
import math

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 光斑位置 + 大小
# ═══════════════════════════════════════════════════════════════════
def compute_patch_geometry(light, window_side: str = "right", cfg=None):
    """
    修改 light 的以下属性：
      patch_center_x, patch_center_y
      patch_width, patch_height
      patch_shear_x, patch_shear_y
      irradiance（乘入射因子）
    """
    if cfg is None:
        cfg = config.get_lighting()

    win_az = config.WINDOW_SIDE_AZ.get(window_side, 90)
    az_rel = light.az - win_az
    while az_rel > 180: az_rel -= 360
    while az_rel < -180: az_rel += 360

    # 入射因子：窗口透射 ∝ cos(alt)·cos(az_rel)
    # （垂直窗面的法线为水平，故需同时乘 cos(alt)）
    # 掠射时趋近 0；下限 0.02 仅避免数值完全归零
    incidence_cos = (math.cos(math.radians(az_rel))
                     * math.cos(math.radians(light.alt)))
    inc_factor = max(0.02, max(0.0, incidence_cos) ** 0.5)
    light.irradiance *= inc_factor
    config.LOG.param("入射因子",
                     f"az_rel={az_rel:.1f}° cos={incidence_cos:.3f} "
                     f"→ {inc_factor:.3f}")

    # 水平位置（光源偏侧 → 光斑偏移）
    h_offset = -math.sin(math.radians(az_rel)) * 0.35
    cx = 0.5 + h_offset

    # 垂直位置（高度角越高越靠上）
    alt_n = min(1.0, max(0.0, light.alt / 60.0))
    cy = 0.55 - alt_n * 0.25

    light.patch_center_x = max(0.05, min(0.95, cx))
    light.patch_center_y = max(0.05, min(0.95, cy))

    # 光斑形状：高/宽 = window_aspect / tan(alt)
    window_aspect = float(cfg.get("window_aspect", 1.5))
    stretch_min = float(cfg.get("stretch_min", 0.5))
    stretch_max = float(cfg.get("stretch_max", 3.5))

    alt_clamped = max(3.0, light.alt)
    stretch = window_aspect / math.tan(math.radians(alt_clamped))
    stretch_norm = max(stretch_min, min(stretch_max, stretch))

    base_w = 0.35
    base_h = base_w * stretch_norm
    light.patch_width = max(0.15, min(0.85, base_w))
    light.patch_height = max(0.15, min(0.95, base_h))

    config.LOG.param("光斑形状",
                     f"alt={light.alt:.1f}° stretch={stretch:.2f} → "
                     f"w={light.patch_width:.2f} h={light.patch_height:.2f}")

    # 剪切（平行四边形）
    light.patch_shear_x = math.cos(math.radians(az_rel)) * 0.15
    light.patch_shear_y = (1.0 - alt_n) * 0.10


# ═══════════════════════════════════════════════════════════════════
# 半影
# ═══════════════════════════════════════════════════════════════════
def compute_penumbra(light, weather):
    """
    物理半影：晴天 0.53° 太阳 → 屏高 0.6%。
    修改 light.penumbra_ratio。
    """
    penumbra_ratio = 0.0060

    if weather.cloud > 30:
        penumbra_ratio += (weather.cloud - 30) / 70.0 * 0.030
    if weather.vis < 5000:
        penumbra_ratio += (5000 - weather.vis) / 5000.0 * 0.020
    if light.source == "moon":
        penumbra_ratio *= 0.7

    # 天气光质「硬度」：在物理半影之上再按天气微调
    # （hard=1 晴天 → ×1.0；纯漫射天气 hard→0 → 更柔和）
    hard = float(getattr(light, "hardness", 1.0) or 1.0)
    penumbra_ratio *= (1.0 + (1.0 - max(0.0, min(1.0, hard))) * 0.8)

    light.penumbra_ratio = max(0.002, min(0.08, penumbra_ratio))
    config.LOG.param("半影比例",
                     f"{light.penumbra_ratio:.4f} "
                     f"(× H = {light.penumbra_ratio * 100:.2f}% 屏高)")


# ═══════════════════════════════════════════════════════════════════
# 阴影
# ═══════════════════════════════════════════════════════════════════
def compute_shadow(alt, az, shadow_length="auto"):
    """返回 (dx, dy)，屏幕归一化比例。"""
    if alt <= 0:
        return 0.0, 0.0
    alt_rad = math.radians(max(1, alt))
    base_len = 1.0 / math.tan(alt_rad)
    len_norm = 0.0005 + min(1.0, base_len / 6.0) * 0.0025
    if shadow_length != "auto":
        try:
            mul = max(0.5, min(4.0, float(shadow_length)))
            len_norm *= mul
        except (ValueError, TypeError):
            pass
    dx = -math.sin(math.radians(az)) * len_norm
    dy = len_norm
    return dx, dy