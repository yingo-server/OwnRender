#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3D 场景中间层 + Blender 后端的守门测试。

本地没有 Blender 也能测（这是关键）：
  · 生成的 bpy 脚本必须是**合法 Python**（ast.parse）
  · 物理量必须真的进了脚本：太阳**角直径**、相机焦距/传感器、水膜 IOR、倾斜面朝向
  · SceneSpec 校验必须拦住非法场景（6 面全镜面、u/v 不正交、越界粗糙度）
"""
import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ownrender.render3d import blender as BL        # noqa: E402
from ownrender.render3d.scene import (CameraSpec, Quad, SceneSpec,    # noqa: E402
                                      SunSpec, WaterFilm)
from ownrender.scene3d.room import Room              # noqa: E402


def _room_spec():
    r = Room(4.0, 3.0, 4.0)
    r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    return SceneSpec.from_room(r, text_face="back")


def test_script_is_valid_python():
    spec = _room_spec()
    src = BL.build_script(spec, "/tmp/ow_test.png")
    ast.parse(src)                                   # 语法必须合法
    assert "import bpy" in src


def test_sun_is_area_light():
    """★ 太阳必须是面光源：脚本里写入了角直径（弧度）。"""
    spec = _room_spec()
    spec.sun = SunSpec(altitude_deg=12.0, azimuth_deg=95.0,
                       angular_diameter_deg=0.5334)
    src = BL.build_script(spec, "/tmp/x.png")
    assert "sun_data.angle = math.radians(0.533400)" in src
    assert "type='SUN'" in src


def test_camera_params_into_script():
    spec = _room_spec()
    spec.camera = CameraSpec(focal_length_mm=85.0, sensor_width_mm=24.0,
                             position=(0.0, 1.6, 2.4))
    src = BL.build_script(spec, "/tmp/x.png")
    assert "cam_data.lens = 85.0000" in src
    assert "cam_data.sensor_width = 24.0000" in src
    assert "cam_obj.location = (0.000000, 1.600000, 2.400000)" in src


def test_tilted_wall_supported():
    """倾斜墙面：任意 u/v 基下的四边形都要能生成，且法线正确。"""
    tilt = np.array([0.0, np.cos(np.radians(20.0)), np.sin(np.radians(20.0))])
    q = Quad(name="tilt", center=[0, 1.5, 0], u=[1, 0, 0], v=tilt,
             size_u=3.0, size_v=2.0)
    spec = SceneSpec(quads=[q])
    assert spec.validate() == [], spec.validate()
    src = BL.build_script(spec, "/tmp/x.png")
    ast.parse(src)
    n = np.asarray(q.normal)
    assert abs(float(n @ np.asarray(q.u))) < 1e-9    # 法线 ⟂ u
    assert abs(float(n @ np.asarray(q.v))) < 1e-9    # 法线 ⟂ v
    # 法线确实倾斜（不是纯 ±Z）
    assert abs(float(n[2])) < 0.999


def test_water_film_layer_in_script():
    spec = _room_spec()
    spec.quads[0].water = WaterFilm(enabled=True, roughness=0.04, ior=1.333,
                                    coverage=0.6)
    src = BL.build_script(spec, "/tmp/x.png")
    assert "wbsdf" in src
    assert "wbsdf.inputs['IOR'].default_value = 1.3330" in src
    assert "mix.inputs[0].default_value = 0.6000" in src    # 覆盖率


def test_validate_rejects_bad_scene():
    # u/v 不正交
    bad = SceneSpec(quads=[Quad(name="q", center=[0, 0, 0], u=[1, 0, 0],
                                v=[1, 1, 0], size_u=1, size_v=1)])
    assert bad.validate()
    # 6 面全镜面
    from ownrender.render3d.scene import MaterialSpec
    quads = []
    for i, n in enumerate([(1, 0, 0), (-1, 0, 0), (0, 1, 0),
                           (0, -1, 0), (0, 0, 1), (0, 0, -1)]):
        u = np.array([0, 1, 0]) if abs(n[1]) != 1 else np.array([1, 0, 0])
        v = np.cross(np.array(n, float), u)
        quads.append(Quad(name="m%d" % i, center=np.array(n, float) * 2.0,
                          u=u, v=v, size_u=4.0, size_v=4.0,
                          material=MaterialSpec(roughness=0.02, specular=0.9)))
    s2 = SceneSpec(quads=quads)
    assert any("镜面" in b for b in s2.validate())


def test_summary_and_json():
    spec = _room_spec()
    spec.quads[1].water.enabled = True
    txt = spec.summary()
    assert "面 6" in txt and "水膜 1" in txt and "叠字目标 1" in txt
    import json
    d = json.loads(spec.to_json())
    assert len(d["quads"]) == 6
    assert "normal" in d["quads"][0] and "corners" in d["quads"][0]


def test_backend_probe_does_not_crash():
    """没装 Blender 时必须优雅报告不可用，而不是崩。"""
    ok = BL.available()
    assert isinstance(ok, bool)