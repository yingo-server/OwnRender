#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天空穹顶的物理守门测试（关键是**能量一致**）。"""
import math

import numpy as np

from ownrender.light import sky


def test_dome_samples_equal_solid_angle():
    dirs, omega = sky.dome_samples(36, 9)
    assert len(dirs) == 36 * 9
    assert abs(float(omega.sum()) - 2 * math.pi) < 1e-12      # 半球 = 2π
    assert np.allclose(omega, omega[0])                       # 等立体角
    assert np.allclose(np.linalg.norm(dirs, axis=1), 1.0, atol=1e-12)
    assert np.all(dirs[:, 1] > -1e-12)                        # 全在上半球


def test_cie_overcast_shape():
    t = np.array([0.0, math.pi / 2])                          # 天顶 / 地平线
    s = sky.radiance_shape(t, "overcast")
    assert s[0] > s[1] * 2.9                                  # 天顶比地平线亮 ~3 倍
    assert abs(s[0] - 1.0) < 1e-9                             # 天顶 = 1·Lz


def test_clear_sky_horizon_brighter():
    t = np.array([0.0, math.pi / 2])
    s = sky.radiance_shape(t, "clear", sun_alt_deg=45.0)
    assert s[1] > s[0], "晴天低空视线更长 → 地平线更亮"


def test_energy_consistency_all_kinds():
    """★ 核心：穹顶积分必须等于天气模型给的水平漫射照度（1e-9）。"""
    dirs, omega = sky.dome_samples(48, 16)
    for kind in ("overcast", "clear", "haze"):
        for E in (0.05, 0.2, 0.9):
            L, Lz = sky.dome_radiance(dirs, omega, E, kind, 45.0)
            got = sky.horizontal_irradiance_check(dirs, omega, L)
            assert abs(got - E) < 1e-9, (kind, E, got)
            assert Lz > 0


def test_radiance_fn_matches_dome():
    # 容差 1e-3：Lz 用 72×18 网格标定，这里用 48×16 网格积分 → 会有
    # 千分之一量级的**数值积分差**（不是模型误差）。
    fn, Lz = sky.make_radiance_fn("overcast", 0.2)
    dirs, omega = sky.dome_samples(48, 16)
    L = fn(dirs)
    assert abs(sky.horizontal_irradiance_check(dirs, omega, L) - 0.2) < 1e-3
    # 地平线以下的方向 = 0
    below = np.array([[0.0, -1.0, 0.0], [0.5, -0.5, 0.0]])
    assert np.allclose(fn(below), 0.0)


def test_linearity_in_diffuse():
    dirs, omega = sky.dome_samples(24, 8)
    L1, _ = sky.dome_radiance(dirs, omega, 0.1, "overcast")
    L2, _ = sky.dome_radiance(dirs, omega, 0.3, "overcast")
    assert np.allclose(L2, 3.0 * L1, rtol=1e-9)