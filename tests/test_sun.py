#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太阳面光源的物理守门测试（见 agent.md §12）。

这些测试只检查**物理必须成立的性质**，不检查"好不好看"：
  · 视直径随距离反比
  · 半影宽度随距离单调变宽、与角直径成正比
  · 软阴影剖面能量守恒（两端分别趋 1 / 0，单调）
  · 局部遮挡：全遮 / 不遮 / 中间值连续且单调
  · 圆盘采样等面积（权重和 = 1，质心 ≈ 0）
"""
import math

import numpy as np
import pytest

from ownrender.light import sun


def test_angular_diameter():
    assert abs(sun.angular_diameter_deg(1.0) - 0.5334) < 1e-9
    # 近日点（d<1）视直径更大
    assert sun.angular_diameter_deg(0.9833) > sun.angular_diameter_deg(1.0167)


def test_penumbra_monotonic_in_distance():
    w = [sun.penumbra_width_m(d) for d in (0.5, 1.0, 2.0, 4.0, 8.0)]
    assert all(w[i] < w[i + 1] for i in range(len(w) - 1)), w
    # 线性：2 倍距离 ≈ 2 倍半影
    assert abs(w[3] / w[1] - 4.0) < 1e-6


def test_penumbra_magnitude():
    # 4 m 距离处半影带宽 ≈ 4·tan(0.2667°) ≈ 18.6 mm
    assert 0.015 < sun.penumbra_width_m(4.0) < 0.022


def test_disc_samples_equal_area():
    n = 64
    pts = sun.disc_samples(n)
    assert pts.shape == (n, 2)
    r = np.linalg.norm(pts, axis=1)
    assert r.max() < 1.0 + 1e-9
    # 质心应接近圆心
    assert abs(float(pts[:, 0].mean())) < 0.05
    assert abs(float(pts[:, 1].mean())) < 0.05
    # 半径平方均匀 → 面积均匀
    assert abs(float((r ** 2).mean()) - 0.5) < 0.02
    assert abs(float(sun.disc_areal_weights(n).sum()) - 1.0) < 1e-12


def test_soft_shadow_endpoints_and_monotone():
    x = np.linspace(-1.0, 1.0, 41)
    y = sun.soft_shadow_profile(x, 0.25)
    assert y[0] > 0.99 and y[-1] < 0.01          # 两端饱和
    assert np.all(np.diff(y) <= 1e-9)            # 单调不增
    # 能量守恒：与硬边阶跃的积分相同（数值上）
    assert abs(float(y.sum()) - float((x < 0).sum())) <= 2.0


def test_soft_shadow_hard_limit():
    x = np.array([-0.5, 0.0, 0.5])
    y = sun.soft_shadow_profile(x, 0.0)
    assert list(y) == [1.0, 0.0, 0.0]            # 硬边


def test_overlap_cases():
    # 不遮
    assert sun.disc_circle_overlap_frac(5.0, 0.5) == 1.0
    # 完全遮住（遮挡物更大）
    assert sun.disc_circle_overlap_frac(0.0, 1.5) == 0.0
    # 中间值连续且随距离单调
    vals = [sun.disc_circle_overlap_frac(d, 0.6) for d in (0.0, 0.2, 0.4, 0.8, 1.6)]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)), vals
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_limb_darkening_bounded():
    mu = np.linspace(0.0, 1.0, 11)
    I = sun.limb_darkening(mu)
    assert abs(float(I[-1]) - 1.0) < 1e-9         # 中心 = 1
    assert float(I[0]) < float(I[-1])             # 边缘更暗
    assert np.all(I >= 0.0)