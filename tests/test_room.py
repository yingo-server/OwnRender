#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""房间几何 + 开口积分的物理守门测试。"""
import numpy as np

from ownrender.scene3d.room import MATERIALS, Room


def test_room_faces_geometry():
    r = Room(4.0, 3.0, 4.0)
    assert set(r.faces) == {"back", "front", "left", "right", "floor", "ceil"}
    assert abs(r.faces["back"].area - 4.0 * 3.0) < 1e-9
    assert abs(r.faces["floor"].area - 4.0 * 4.0) < 1e-9
    for f in r.faces.values():
        assert abs(float(np.linalg.norm(f.normal)) - 1.0) < 1e-9
        assert abs(float(np.linalg.norm(f.u)) - 1.0) < 1e-9
        assert abs(float(f.u @ f.v)) < 1e-9          # 正交


def test_validate_rejects_all_mirror_room():
    r = Room(4.0, 3.0, 4.0, {k: "mirror" for k in
                             ("back", "front", "left", "right", "floor", "ceil")})
    bad = r.validate()
    assert bad, "6 面全镜面必须被拒绝"
    assert any("镜面" in b for b in bad)


def test_validate_window_bounds():
    r = Room(4.0, 3.0, 4.0)
    r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    assert r.validate() == []
    r2 = Room(4.0, 3.0, 4.0)
    r2.add_window("right", 0.0, 0.0, 99.0, 1.5)     # 超出墙
    assert r2.validate()


def test_opening_irradiance_positive_and_monotone():
    """地板受侧窗照：离窗越远越暗（严格单调）。

    注意：**与窗面平行的那面墙几乎收不到直射**（d̂ 与墙法线近乎垂直，
    cos→0）—— 这是物理，不是 bug。侧窗的光主要落在地板、对面墙与天花板上。
    """
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    n_floor = np.array([0.0, 1.0, 0.0])             # 地板法线朝上（朝房间内）
    const = lambda d: np.ones((len(d), 3))          # noqa: E731  常亮天空 L=1
    Es = []
    for x in (0.0, -0.5, -1.0, -1.5):
        P = np.array([x, 0.0, 2.0])                 # 地板上、沿 x 远离窗
        Es.append(float(r.irradiance_from_opening(P, n_floor, op, const)[0]))
    assert all(e > 0 for e in Es), Es
    assert all(Es[i] > Es[i + 1] for i in range(len(Es) - 1)), Es


def test_reversed_normal_receives_nothing():
    """背光面（法线朝背离窗户的一侧）照度 = 0。"""
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    P = np.array([0.0, 1.5, 0.02])
    E = float(r.irradiance_from_opening(
        P, np.array([0.0, 0.0, -1.0]), op,
        lambda d: np.ones((len(d), 3)))[0])
    assert E == 0.0, E


def test_oblique_wall_receives_some():
    """与窗面**垂直**的墙：因为窗在 z 方向有偏移，仍会收到斜射光（>0）。"""
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    E = float(r.irradiance_from_opening(
        np.array([0.0, 1.5, 0.02]), np.array([0.0, 0.0, 1.0]), op,
        lambda d: np.ones((len(d), 3)))[0])
    assert E > 0.01, E


def test_opening_irradiance_linear_in_radiance():
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    n = np.array([0.0, 1.0, 0.0])
    P = np.array([0.0, 0.0, 2.0])
    E1 = r.irradiance_from_opening(P, n, op, lambda d: np.ones((len(d), 3)))
    E3 = r.irradiance_from_opening(P, n, op, lambda d: np.full((len(d), 3), 3.0))
    assert np.allclose(E3, 3.0 * E1, rtol=1e-9), (E1, E3)


def test_opening_irradiance_zero_behind():
    """点在窗面外侧（x > W/2）→ 收不到窗内的光。"""
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    n = np.array([1.0, 0.0, 0.0])                   # 法线朝 -X 才对得上，这里故意反
    P = np.array([r.w / 2 + 0.5, 1.5, 2.0])
    E = r.irradiance_from_opening(P, n, op, lambda d: np.ones((len(d), 3)))
    assert float(E[0]) < 1e-9, E


def test_opening_irradiance_converges_with_sampling():
    r = Room(4.0, 3.0, 4.0)
    op = r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    n = np.array([0.0, 1.0, 0.0])
    P = np.array([0.5, 0.0, 1.2])
    const = lambda d: np.ones((len(d), 3))          # noqa: E731
    E_coarse = float(r.irradiance_from_opening(P, n, op, const, samples=(6, 5))[0])
    E_fine = float(r.irradiance_from_opening(P, n, op, const, samples=(60, 50))[0])
    assert abs(E_fine - E_coarse) / E_fine < 0.12, (E_coarse, E_fine)


def test_room_roundtrip():
    r = Room(4.0, 3.0, 4.0, {"back": "cement"})
    r.add_window("right", 0.1, -0.2, 1.0, 1.4)
    d = r.to_dict()
    r2 = Room.from_dict(d)
    assert r2.to_dict()["dims"] == d["dims"]
    assert r2.openings[0].size_u == 1.0
    assert r2.faces["back"].material.name == "cement"