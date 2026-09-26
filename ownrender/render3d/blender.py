#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blender（Cycles）后端 —— 我们只写"翻译器"，不写渲染器。

职责边界（agent.md §16）
    我们：SceneSpec → bpy 脚本（几何/材质/光源/相机/渲染设置）+ 调用 + 收产物
    Blender：光线传输、BVH、采样、去噪、色彩管理、编解码

关键物理对应
    · 太阳 = **面光源**：Blender 的 SUN 灯有 `angle`（角直径，弧度）→ 半影自然正确
    · 天空 = 穹顶：World 节点用环境纹理/渐变；阴天用 CIE 形状的自定义节点组
    · 水膜 = 单独一层薄片（IOR=1.333、可给粗糙度/覆盖率掩膜）→ 水渍/水痕
    · 倾斜墙面 = 任意 u/v 基下的四边形（法线任意）—— 由 SceneSpec 决定
    · 叠字：既可 3D Text 对象贴到目标面，也可渲染后交给现有叠字管线（默认后者）
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .scene import SceneSpec

BLENDER_ENV_HINT = "OWNRENDER_BLENDER"


# ═══════════════════════════════════════════════════════════════════
# 探测
# ═══════════════════════════════════════════════════════════════════
def find_blender() -> Optional[str]:
    """找 blender 可执行文件：环境变量 > PATH。"""
    env = os.environ.get(BLENDER_ENV_HINT)
    if env and Path(env).exists():
        return env
    return shutil.which("blender")


def available() -> bool:
    return find_blender() is not None


# ═══════════════════════════════════════════════════════════════════
# 脚本生成（纯字符串；可被单测 ast.parse 验证）
# ═══════════════════════════════════════════════════════════════════
def _mat_nodes(m, water, indent="    ") -> str:
    """生成 Principled BSDF 材质节点代码（含可选水膜层）。"""
    L = []
    a = L.append
    rgb = list(m.albedo)
    a("%sbsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')" % indent)
    a("%sbsdf.inputs['Base Color'].default_value = (%.4f, %.4f, %.4f, 1.0)"
      % (indent, rgb[0], rgb[1], rgb[2]))
    a("%sbsdf.inputs['Roughness'].default_value = %.4f" % (indent, m.roughness))
    a("%sbsdf.inputs['Metallic'].default_value = %.4f" % (indent, m.metallic))
    a("%sbsdf.inputs['IOR'].default_value = %.4f" % (indent, m.ior))
    a("%sbsdf.inputs['Transmission Weight'].default_value = %.4f"
      % (indent, m.transmission))
    a("%sif 'Specular IOR Level' in bsdf.inputs:" % indent)
    a("%s    bsdf.inputs['Specular IOR Level'].default_value = %.4f"
      % (indent, m.specular))
    # 法线贴图（可选）
    if m.normal_map:
        a("%sntex = nt.nodes.new('ShaderNodeTexImage')" % indent)
        a("%sntex.image = bpy.data.images.load('%s')" % (indent, m.normal_map))
        a("%snmap = nt.nodes.new('ShaderNodeNormalMap')" % indent)
        a("%snmap.inputs['Strength'].default_value = %.4f" % (indent, m.normal_strength))
        a("%snt.links.new(ntex.outputs['Color'], nmap.inputs['Color'])" % indent)
        a("%snt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])" % indent)
    if m.albedo_map:
        a("%satex = nt.nodes.new('ShaderNodeTexImage')" % indent)
        a("%satex.image = bpy.data.images.load('%s')" % (indent, m.albedo_map))
        a("%snt.links.new(atex.outputs['Color'], bsdf.inputs['Base Color'])" % indent)
    # 水膜：混入一个水材质（IOR 1.333，低粗糙）
    if water is not None and water.enabled:
        a("%swbsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')" % indent)
        a("%swbsdf.inputs['Base Color'].default_value = (1.0, 1.0, 1.0, 1.0)")
        a("%swbsdf.inputs['Roughness'].default_value = %.4f" % (indent, water.roughness))
        a("%swbsdf.inputs['IOR'].default_value = %.4f" % (indent, water.ior))
        a("%sif 'Transmission Weight' in wbsdf.inputs:" % indent)
        a("%s    wbsdf.inputs['Transmission Weight'].default_value = 1.0" % indent)
        a("%smix = nt.nodes.new('ShaderNodeMixShader')" % indent)
        a("%smix.inputs[0].default_value = %.4f   # 水膜覆盖率（wet coverage）"
          % (indent, water.coverage))
        a("%snt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])" % indent)
        a("%snt.links.new(wbsdf.outputs['BSDF'], mix.inputs[2])" % indent)
        a("%snt.links.new(mix.outputs['Shader'], out.inputs['Surface'])" % indent)
    else:
        a("%snt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])" % indent)
    return "\n".join(L)


def _quad_code(q, idx: int) -> str:
    """用四个角点建面（任意朝向 → 自动支持倾斜墙）。"""
    c = q.corners()
    lines = [
        "    verts = [%s]" % ", ".join("(%.6f, %.6f, %.6f)" % tuple(p) for p in c),
        "    mesh = bpy.data.meshes.new('%s_mesh')" % q.name,
        "    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])",
        "    mesh.update()",
        "    obj = bpy.data.objects.new('%s', mesh)" % q.name,
        "    bpy.context.collection.objects.link(obj)",
        "    m = bpy.data.materials.new('mat_%s')" % q.name,
        "    m.use_nodes = True",
        "    nt = m.node_tree",
        "    out = nt.nodes.get('Material Output') or nt.nodes.new('ShaderNodeOutputMaterial')",
    ]
    body = _mat_nodes(q.material, q.water)
    lines.append(body)
    lines.append("    obj.data.materials.append(m)")
    if q.text_target:
        lines.append("    # 叠字目标面")
    return "\n".join(lines)


def _sky_world_code(spec: SceneSpec) -> str:
    """天空穹顶：World 背景。阴天用 CIE 形状的 Gradient 近似；晴天可换 Sky Texture。"""
    s = spec.sky
    L = []
    L.append("    world = bpy.data.worlds.new('ow_world')")
    L.append("    bpy.context.scene.world = world")
    L.append("    world.use_nodes = True")
    L.append("    wnt = world.node_tree")
    L.append("    bg = wnt.nodes.get('Background') or wnt.nodes.new('ShaderNodeBackground')")
    L.append("    wout = wnt.nodes.get('World Output') or wnt.nodes.new('ShaderNodeOutputWorld')")
    if s.use_texture:
        L.append("    sky = wnt.nodes.new('ShaderNodeTexSky')")
        L.append("    sky.sky_type = 'NISHITA'")
        L.append("    sky.turbidity = %.3f" % s.turbidity)
        L.append("    sky.sun_elevation = %.5f" % (spec.sun.altitude_deg * 3.141592653589793 / 180.0))
        L.append("    sky.sun_rotation = %.5f" % (spec.sun.azimuth_deg * 3.141592653589793 / 180.0 + 1.5707963267948966))
        L.append("    wnt.links.new(sky.outputs['Color'], bg.inputs['Color'])")
    else:
        # 阴天/霾：天顶亮、地平线暗的 CIE 形状（用 Gradient + 幂次近似）
        L.append("    grad = wnt.nodes.new('ShaderNodeTexGradient')")
        L.append("    grad.gradient_type = 'LINEAR'")
        L.append("    ramp = wnt.nodes.new('ShaderNodeValToRGB')")
        L.append("    ramp.color_ramp.elements[0].position = 0.0")
        L.append("    ramp.color_ramp.elements[0].color = (%.5f, %.5f, %.5f, 1.0)"
                 % (s.zenith_radiance, s.zenith_radiance * 1.05,
                    s.zenith_radiance * 1.15))
        L.append("    ramp.color_ramp.elements[1].position = 1.0")
        L.append("    ramp.color_ramp.elements[1].color = (%.5f, %.5f, %.5f, 1.0)"
                 % (s.zenith_radiance / 3.0, s.zenith_radiance / 3.0 * 1.1,
                    s.zenith_radiance / 3.0 * 1.25))
        L.append("    wnt.links.new(grad.outputs['Fac'], ramp.inputs['Fac'])")
        L.append("    wnt.links.new(ramp.outputs['Color'], bg.inputs['Color'])")
    L.append("    bg.inputs['Strength'].default_value = 1.0")
    L.append("    wnt.links.new(bg.outputs['Background'], wout.inputs['Surface'])")
    return "\n".join(L)


def build_script(spec: SceneSpec, out_png: str) -> str:
    """把 SceneSpec 翻译成 Blender Python 脚本（纯字符串，可单测）。

    结构（重要）：所有场景搭建都放进 `def build():`，再在顶层调用 ——
    这样几何/材质/灯光代码统一 4 空格缩进，既合法又不会被 Blender 拒绝。
    """
    bad = spec.validate()
    if bad:
        raise ValueError("场景不合法：%s" % "；".join(bad))

    sun = spec.sun
    cam = spec.camera
    r = spec.render
    L: List[str] = []
    a = L.append

    def a4(s: str = "") -> None:
        a(("    " + s) if s else "")

    a("# -*- coding: utf-8 -*-")
    a("# 由 OwnRender 自动生成（ownrender/render3d/blender.py）—— 勿手改")
    a("import bpy, math")
    a("import mathutils")
    a("")
    a("def clear_scene():")
    a("    bpy.ops.wm.read_factory_settings(use_empty=True)")
    a("")
    a("def build():")
    a("    clear_scene()")
    a("")
    a4("# ── 几何（任意朝向的面：斜墙/天花板/地板都走同一条路）──")
    for i, q in enumerate(spec.quads):
        a(_quad_code(q, i))
        a("")
    a4("# ── 天空（穹顶光源）──")
    a(_sky_world_code(spec))
    a("")
    a4("# ── 太阳：**面光源**（angle = 角直径，决定半影）──")
    a4("sun_data = bpy.data.lights.new('ow_sun', type='SUN')")
    a4("sun_data.angle = math.radians(%.6f)      # ★ 视直径 → 软阴影"
       % sun.angular_diameter_deg)
    a4("sun_data.energy = %.6f" % max(0.0, sun.irradiance))
    a4("sun_data.color = (%.4f, %.4f, %.4f)" % tuple(sun.color_rgb))
    a4("sun_obj = bpy.data.objects.new('ow_sun', sun_data)")
    a4("bpy.context.collection.objects.link(sun_obj)")
    a4("alt = math.radians(%.4f)" % sun.altitude_deg)
    a4("azi = math.radians(%.4f)" % sun.azimuth_deg)
    a4("sun_obj.rotation_euler = (math.pi / 2.0 - alt, 0.0, azi)")
    a("")
    a4("# ── 相机（按注册表：焦距/传感器/光圈/快门/ISO）──")
    a4("cam_data = bpy.data.cameras.new('ow_cam')")
    a4("cam_data.lens = %.4f" % cam.focal_length_mm)
    a4("cam_data.sensor_width = %.4f" % cam.sensor_width_mm)
    a4("cam_data.clip_start = 0.01")
    a4("cam_data.clip_end = 1000.0")
    a4("cam_obj = bpy.data.objects.new('ow_cam', cam_data)")
    a4("bpy.context.collection.objects.link(cam_obj)")
    a4("bpy.context.scene.camera = cam_obj")
    a4("cam_obj.location = (%.6f, %.6f, %.6f)" % tuple(cam.position))
    a4("_look = (%.6f, %.6f, %.6f)" % tuple(cam.look_at))
    a4("_dir = (_look[0] - cam_obj.location[0],"
       " _look[1] - cam_obj.location[1], _look[2] - cam_obj.location[2])")
    a4("_q = mathutils.Vector(_dir).to_track_quat('-Z', 'Y')")
    a4("cam_obj.rotation_euler = _q.to_euler()")
    a("")
    a4("# ── 渲染设置（Cycles / CPU / 采样 / 去噪 / 色彩管理）──")
    a4("sc = bpy.context.scene")
    a4("sc.render.engine = '%s'" % r.engine)
    a4("if hasattr(sc, 'cycles'):")
    a4("    sc.cycles.device = '%s'" % r.device)
    a4("    sc.cycles.samples = %d" % int(r.samples))
    a4("    sc.cycles.use_denoising = %s" % ("True" if r.use_denoise else "False"))
    a4("    try:")
    a4("        sc.cycles.seed = %d" % int(spec.seed))
    a4("    except Exception:")
    a4("        pass")
    a4("sc.render.resolution_x = %d" % int(r.resolution[0]))
    a4("sc.render.resolution_y = %d" % int(r.resolution[1]))
    a4("sc.render.resolution_percentage = 100")
    a4("sc.render.image_settings.file_format = 'PNG'")
    a4("sc.render.image_settings.color_mode = 'RGB'")
    a4("sc.render.image_settings.color_depth = '16'")
    a4("sc.render.film_transparent = %s"
       % ("True" if r.transparent_film else "False"))
    a4("try:")
    a4("    sc.view_settings.view_transform = '%s'" % r.view_transform)
    a4("except Exception:")
    a4("    pass")
    a("")
    a4("# ── 输出 ──")
    a4("sc.render.filepath = r'%s'" % out_png)
    a4("bpy.ops.render.render(write_still=True)")
    a("")
    a("build()")
    a("print('OWNRENDER_OK %s')" % out_png)
    return "\n".join(L) + "\n"


# ═══════════════════════════════════════════════════════════════════
# 调用
# ═══════════════════════════════════════════════════════════════════
def render(spec: SceneSpec, out_png: str, *, blender: Optional[str] = None,
           timeout_s: int = 3600, extra_args: Optional[List[str]] = None
           ) -> str:
    """跑一次 Blender headless 渲染。返回 PNG 路径（失败抛异常）。"""
    exe = blender or find_blender()
    if not exe:
        raise RuntimeError(
            "找不到 blender。CI 里可 `apt-get install -y blender`，"
            "或用 %s 指定路径（agent.md §16）。" % BLENDER_ENV_HINT)
    script = build_script(spec, out_png)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        sp = f.name
    cmd = [exe, "-b", "--factory-startup", "-noaudio", "-P", sp]
    if extra_args:
        cmd += extra_args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if p.returncode != 0 or not Path(out_png).exists():
            tail = (p.stdout or "")[-1500:] + (p.stderr or "")[-1500:]
            raise RuntimeError("Blender 渲染失败（exit=%d）：\n%s" % (p.returncode, tail))
        return out_png
    finally:
        try:
            os.unlink(sp)
        except OSError:
            pass


def _self_test():                                            # pragma: no cover
    from ownrender.scene3d.room import Room
    from .scene import SceneSpec
    r = Room(4.0, 3.0, 4.0)
    r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    spec = SceneSpec.from_room(r)
    spec.quads[0].water.enabled = True
    script = build_script(spec, "/tmp/ow_blender_test.png")
    print("脚本行数：", len(script.splitlines()))
    print("含 SUN 角直径：", "sun_data.angle" in script)
    print("含水膜层    ：", "wbsdf" in script)
    print("blender 可用：", available())


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()