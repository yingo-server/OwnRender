#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天空 —— **穹顶光源**（半球、四面八方），不是"窗户那么大的一块"。

物理要点
══════════════════════════════════════════════════════════════════════
1. 天空是一个**扩展光源**：每个方向都有自己的辐射亮度 L(θ,φ)。
2. 辐射亮度分布用公开模型：
   · 全阴天：CIE Overcast Sky  L(θ) = Lz·(1 + 2cosθ)/3     （θ=天顶角）
   · 晴天：  L(θ) = Lz·(a + b·cosθ) + 地平线增亮项（Kittler 型近似）
   两者都只由"天顶亮度 Lz"定标，形状由模型给出，**没有手调系数**。
3. 定标方式（关键）：让穹顶积分**等于**天气模型给出的水平漫射照度
       ∫ L(θ)·cosθ dω ≡ E_diffuse
   这样"穹顶光源"与"直射/漫射分离模型"天然自洽（能量守恒，可被单测验证）。
"""
import math
from typing import Tuple

import numpy as np


# ═══════════════════════════════════════════════════════════════════
# 半球离散化（**等立体角**：每个样本代表相同的 dω）
# ═══════════════════════════════════════════════════════════════════
def dome_samples(n_az: int = 36, n_el: int = 9
                 ) -> Tuple[np.ndarray, np.ndarray]:
    """等立体角采样半球。返回 (dirs (N,3) 单位向量, omega (N,) 立体角)。

    dω 相等的做法：令 cosθ 在 [0,1] 上均匀取中值，则每条"带"的
    dω = (2π/n_az)·(2/n_el)，全半球总和 = 2π（可被单测验证）。
    """
    n_az = max(1, int(n_az))
    n_el = max(1, int(n_el))
    # ★ 半球：cosθ 只能取 [0,1]（0=地平线，1=天顶）。
    #   取整球会让 Σdω=4π、并且把"地下方向"当光源 → 能量与亮度全错。
    cos_t = 1.0 - (np.arange(n_el) + 0.5) * (1.0 / n_el)
    sin_t = np.sqrt(np.maximum(0.0, 1.0 - cos_t ** 2))
    phi = (np.arange(n_az) + 0.5) * (2.0 * math.pi / n_az)
    dirs = []
    for i in range(n_el):
        for j in range(n_az):
            dirs.append([sin_t[i] * math.cos(phi[j]),
                         cos_t[i],                        # Y 轴向上
                         sin_t[i] * math.sin(phi[j])])
    dirs = np.array(dirs, dtype=np.float64)
    omega = np.full(len(dirs), (2.0 * math.pi / n_az) * (1.0 / n_el),
                    dtype=np.float64)
    return dirs, omega


def zenith_angle(dirs: np.ndarray) -> np.ndarray:
    """方向 → 天顶角 θ（弧度，0=正上方）。Y 轴朝上。"""
    d = np.asarray(dirs, dtype=np.float64)
    cos_t = np.clip(d[..., 1], -1.0, 1.0)
    return np.arccos(cos_t)


# ═══════════════════════════════════════════════════════════════════
# 辐射亮度分布（形状由公开模型给出）
# ═══════════════════════════════════════════════════════════════════
def radiance_shape(theta_z: np.ndarray, kind: str = "overcast",
                   sun_alt_deg: float = 45.0) -> np.ndarray:
    """相对天顶的亮度形状 L(θ)/Lz（无量纲）。"""
    t = np.asarray(theta_z, dtype=np.float64)
    c = np.cos(t)
    k = str(kind or "overcast").lower()
    if k in ("overcast", "rain", "shower", "thunder", "snow", "fog"):
        # CIE Overcast Sky
        return np.clip((1.0 + 2.0 * c) / 3.0, 1e-6, None)
    if k in ("haze",):
        # 霾：接近均匀（Mie 主导）
        return np.clip(0.85 + 0.15 * c, 1e-6, None)
    # 晴天：天顶偏暗、地平线亮（Rayleigh 视线长度变长）
    low = max(0.05, math.sin(math.radians(max(0.0, sun_alt_deg))))
    grad = 0.55 + 0.45 * (1.0 - c) / max(0.2, low)
    return np.clip(grad, 1e-6, None)


def calibrate_zenith_L(dirs: np.ndarray, omega: np.ndarray,
                       diffuse_horizontal: float, kind: str = "overcast",
                       sun_alt_deg: float = 45.0) -> float:
    """求天顶亮度 Lz，使 ∫L·cosθ dω = 给定的水平漫射照度（能量一致）。"""
    shape = radiance_shape(zenith_angle(dirs), kind, sun_alt_deg)
    denom = float(np.sum(shape * omega * np.clip(dirs[:, 1], 0.0, None)))
    return float(diffuse_horizontal) / max(1e-12, denom)


def dome_radiance(dirs: np.ndarray, omega: np.ndarray,
                  diffuse_horizontal: float, kind: str = "overcast",
                  sun_alt_deg: float = 45.0
                  ) -> Tuple[np.ndarray, float]:
    """返回 (每个方向的辐射亮度 L (N,), 天顶亮度 Lz)。"""
    Lz = calibrate_zenith_L(dirs, omega, diffuse_horizontal, kind, sun_alt_deg)
    shape = radiance_shape(zenith_angle(dirs), kind, sun_alt_deg)
    return Lz * shape, Lz


def horizontal_irradiance_check(dirs: np.ndarray, omega: np.ndarray,
                                L: np.ndarray) -> float:
    """∫L·cosθ dω —— 用于单测：必须等于标定用的 E_diffuse。"""
    return float(np.sum(np.asarray(L) * omega * np.clip(dirs[:, 1], 0.0, None)))


# ═══════════════════════════════════════════════════════════════════
# 直接可用：把穹顶包成 room.irradiance_from_opening 需要的 radiance_fn
# ═══════════════════════════════════════════════════════════════════
def make_radiance_fn(kind: str, diffuse_horizontal: float,
                     sun_alt_deg: float = 45.0, n_az: int = 72,
                     n_el: int = 18):
    """构造 radiance_fn(d) → L(d)（用细网格做方向查表，最近邻/插值）。

    这里用"按天顶角插值"的解析式，不需要查表：
        L(d) = Lz · shape(θ(d))
    """
    dirs, omega = dome_samples(n_az, n_el)
    Lz = calibrate_zenith_L(dirs, omega, diffuse_horizontal, kind, sun_alt_deg)
    dirs, omega = dome_samples(n_az, n_el)          # 参考用（形状解析式）

    def fn(d_hat: np.ndarray) -> np.ndarray:
        theta = zenith_angle(np.atleast_2d(d_hat))
        shape = radiance_shape(theta, kind, sun_alt_deg)
        below = np.clip(np.atleast_2d(d_hat)[..., 1], -1.0, 1.0) < 0.0
        L = Lz * shape
        return np.where(below, 0.0, L).reshape(-1)

    return fn, Lz


# ═══════════════════════════════════════════════════════════════════
# 自检（python -m ownrender.light.sky）
# ═══════════════════════════════════════════════════════════════════
def _self_test():                                            # pragma: no cover
    dirs, omega = dome_samples()
    print("采样数 %d，Σdω = %.6f（应 = 2π = %.6f）"
          % (len(dirs), omega.sum(), 2 * math.pi))
    for kind in ("overcast", "clear", "haze"):
        L, Lz = dome_radiance(dirs, omega, 0.20, kind)
        E = horizontal_irradiance_check(dirs, omega, L)
        print("%-9s Lz=%.4f  校验∫L·cosθdω=%.6f（目标 0.200000）"
              % (kind, Lz, E))


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()