#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太阳 —— **面光源**（不是点光源）。

为什么这件事是整个重构的核心之一
══════════════════════════════════════════════════════════════════════
把太阳当点光源，投影阴影永远是"硬边"的；但真实太阳有约 0.53° 的视直径，
它在天空里是一个**圆盘**。这带来两个必然结果（用户点名的"有时清晰有时模糊"）：

  1. **本影/半影**：影子的边缘不是一刀切，而是有一段渐变带，
     宽度 ≈ 光源角直径 × 距离：
         半影宽度 W ≈ D · tan(α)，  α = 太阳视直径 ≈ 0.533°
     所以光斑离窗越远 → 边缘越软；太阳越低（大气折射/角直径微变）→ 越软。
  2. **部分遮挡**：遮挡物只挡住圆盘一部分时，照度介于全亮与全暗之间，
     本模块用"圆盘-遮挡物重叠面积"给出精确的中间值。

本模块只做**纯函数 + 纯几何**，不碰图像、不碰配置，便于单测。
"""
import math

import numpy as np

# ── 物理常数（不是可调参数）────────────────────────────────────────
SUN_ANGULAR_DIAMETER_DEG = 0.5334      # 太阳视直径（1 AU 处）
AU_KM = 149_597_870.7                  # 1 天文单位


def angular_diameter_deg(distance_au: float = 1.0) -> float:
    """太阳视直径（度）。地球轨道偏心率使它年变化 ±1.7%：
    θ(d) = θ₁ₐᵤ / d（小角近似，误差 <1e-6）。"""
    d = max(1e-3, float(distance_au))
    return SUN_ANGULAR_DIAMETER_DEG / d


def angular_radius_rad(distance_au: float = 1.0) -> float:
    return math.radians(angular_diameter_deg(distance_au)) / 2.0


def penumbra_width_m(distance_m: float, distance_au: float = 1.0) -> float:
    """半影带宽（米）。distance_m = 遮挡物到受影面的距离。"""
    return abs(float(distance_m)) * math.tan(angular_radius_rad(distance_au))


def penumbra_ratio(distance_m: float, image_size_m: float,
                   distance_au: float = 1.0) -> float:
    """半影宽度占画面尺寸的比例（给渲染器直接用的模糊半径）。"""
    return penumbra_width_m(distance_m, distance_au) / max(1e-6, float(image_size_m))


# ═══════════════════════════════════════════════════════════════════
# 圆盘采样（给"面积光源"采样用）
# ═══════════════════════════════════════════════════════════════════
def disc_samples(n: int = 16) -> np.ndarray:
    """在单位圆盘上取 n 个**等面积**采样点（向日葵螺旋，确定性、无随机）。

    返回 (n, 2)，半径 ∈ [0,1)，面积权重相同 = 1/n。
    用于把太阳圆盘离散成 n 个小光源（面光源采样）。
    """
    n = max(1, int(n))
    k = np.arange(n, dtype=np.float64) + 0.5
    r = np.sqrt(k / n)                                  # 等面积
    phi = k * math.pi * (3.0 - math.sqrt(5.0))          # 黄金角
    return np.stack([r * np.cos(phi), r * np.sin(phi)], axis=1)


def disc_areal_weights(n: int = 16) -> np.ndarray:
    """各采样点权重（等面积 → 全部相等）。"""
    n = max(1, int(n))
    return np.full(n, 1.0 / n, dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════
# 部分遮挡：圆盘 ∩ 遮挡物 的面积占比（= 局部照度比例）
# ═══════════════════════════════════════════════════════════════════
def disc_circle_overlap_frac(d: float, r_occ: float, r_sun: float = 1.0) -> float:
    """半径 r_sun 的太阳圆盘 与 半径 r_occ、圆心距 d 的遮挡圆的交集面积占比。

    d=0 且 r_occ>=r_sun → 0（全遮）
    d >= r_sun+r_occ     → 1（不遮）
    中间 → 解析面积公式（两圆相交），误差仅来自"遮挡物边缘当作直边"的近似。
    """
    d = float(d)
    R, r = float(r_sun), float(r_occ)
    if R <= 0 or r <= 0:
        return 1.0
    if d >= R + r:
        return 1.0
    if d <= abs(R - r):
        return 0.0 if r >= R else 1.0 - (r * r) / (R * R)
    # 两圆相交面积（标准公式）
    d2 = d * d
    a1 = (d2 + R * R - r * r) / (2 * d * R)
    a2 = (d2 + r * r - R * R) / (2 * d * r)
    a1 = max(-1.0, min(1.0, a1))
    a2 = max(-1.0, min(1.0, a2))
    area = (R * R * math.acos(a1) + r * r * math.acos(a2)
            - 0.5 * math.sqrt(max(0.0,
                                  (-d + R + r) * (d + R - r)
                                  * (d - R + r) * (d + R + r))))
    frac = 1.0 - area / (math.pi * R * R)
    return max(0.0, min(1.0, frac))


def soft_shadow_profile(x_rel: np.ndarray, p_soft: float,
                        samples: int = 9) -> np.ndarray:
    """一维软阴影剖面：x_rel ∈ [-1,1]（-1=全亮侧，1=全暗侧）。

    p_soft = 半影宽度占该维度的比例（0 → 硬边阶跃）。
    做法：把太阳圆盘沿该方向离散成 `samples` 条带，每条带给出
    "是否被挡"的阶跃，再按面积权重求和 —— 结果天然满足能量守恒
    （两端分别趋近 1 与 0，且总和与硬边一致）。
    """
    x = np.asarray(x_rel, dtype=np.float64)
    p = max(0.0, float(p_soft))
    if p <= 1e-6:
        return np.where(x < 0.0, 1.0, 0.0)
    n = max(1, int(samples))
    w = disc_areal_weights(n)
    xs = disc_samples(n)[:, 0]          # 沿该方向的偏移 ∈ (-1,1)
    out = np.zeros_like(x)
    # 遮挡边界在 x=0；圆盘各点相对边界的位置 = x - xs*p
    for wi, xi in zip(w, xs):
        out += wi * (x < xi * p).astype(np.float64)
    return np.clip(out, 0.0, 1.0)


def limb_darkening(mu: np.ndarray, u1: float = 0.85,
                   u2: float = -0.15) -> np.ndarray:
    """临边昏暗（太阳边缘比中心暗）。mu = cos(视线与日面法线夹角) ∈ [0,1]。

    二次定律 I(mu)/I(1) = 1 - u1(1-mu) - u2(1-mu)^2
    系数取可见光近似值（物理量，非风格参数）。
    """
    m = np.clip(np.asarray(mu, dtype=np.float64), 0.0, 1.0)
    return np.clip(1.0 - u1 * (1.0 - m) - u2 * (1.0 - m) ** 2, 0.0, 1.0)


# ═══════════════════════════════════════════════════════════════════
# 自检（python -m ownrender.light.sun）
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("太阳视直径        : %.4f°" % angular_diameter_deg(1.0))
    print("远日点/近日点     : %.4f° / %.4f°"
          % (angular_diameter_deg(1.0167), angular_diameter_deg(0.9833)))
    for D in (1.0, 2.0, 4.0):
        print("距离 %.1fm 半影带宽 : %.2f mm" % (D, penumbra_width_m(D) * 1000))
    print("圆盘采样(5)       :", np.round(disc_samples(5), 3).tolist())
    x = np.linspace(-1, 1, 9)
    print("软阴影剖面        :", np.round(soft_shadow_profile(x, 0.3), 2).tolist())
    print("局部遮挡(遮挡圆心距0.5/半径0.6): %.3f"
          % disc_circle_overlap_frac(0.5, 0.6))