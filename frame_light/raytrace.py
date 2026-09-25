#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 逐像素着色（3D 场景 + 材质 + 物理反射）

职责：
  1. 逐像素射线与观察墙求交
  2. 材质采样（albedo / normal / roughness / specular / is_water）
  3. 窗户遮挡判断（直接光可见性）
  4. Cook-Torrance 镜面 BRDF
  5. Fresnel 水面反射
  6. 环境光叠加
  7. 输出线性 RGB 光照图

核心公式：
  漫反射：L_d = ρ × c × max(0, N·L_to_sun) × visible
  镜面：L_s = c × D·G·F / (4·N·L·N·V) × visible × sun_irradiance
  Fresnel：F = F0 + (1-F0)·(1-N·V)^5
  Cook-Torrance D：GGX 分布
  Cook-Torrance G：Smith 几何遮蔽
  环境：L_a = ρ × c_ambient

不 import 本框架其他文件（除 utils + scene3d）。
只 import config + utils + scene3d + 标准库 + numpy。
被 pipeline.py 编排调用。
"""
import math
from typing import Optional, Dict, Any, Tuple

import numpy as np

import config
from . import utils
from . import scene3d as s3
from . import astro


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════
def trace_scene(W: int, H: int,
                light,
                weather,
                scene: s3.Scene3D,
                material: Optional[Dict[str, np.ndarray]] = None,
                sun_color_rgb: Optional[np.ndarray] = None,
                sun_irradiance: float = 1.0,
                working_size: Optional[int] = None,
                progress=None) -> np.ndarray:
    """
    逐像素着色。返回 (H, W, 3) float32 线性 RGB。
    """
    cfg = config.get_lighting()
    rep = utils.report

    # ══════════════════════════════════════════════════════════
    # 阶段 0：工作尺寸
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.02, "确定工作尺寸")
    if working_size is None:
        work_W, work_H = W, H
    else:
        scale = min(1.0, working_size / max(W, H))
        work_W = max(64, int(W * scale))
        work_H = max(64, int(H * scale))

    config.LOG.param("raytrace 工作尺寸", f"{work_W}x{work_H}")

    # ══════════════════════════════════════════════════════════
    # 阶段 1：生成射线
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.10, f"生成射线 {work_W}x{work_H}")
    scene.set_image_size(work_W, work_H)
    origins, dirs = scene.screen_to_ray_batch(work_W, work_H)

    # ══════════════════════════════════════════════════════════
    # 阶段 2：与观察墙求交
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.20, "墙求交")
    hit, P = scene.ray_wall_intersect_batch(origins, dirs)
    valid = hit

    # ══════════════════════════════════════════════════════════
    # 阶段 3：材质采样
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.30, "材质采样")
    mat_work = _resize_material(material, work_W, work_H)

    albedo = mat_work["albedo"]
    normal = mat_work["normal"]
    roughness = mat_work["roughness"]
    specular_tex = mat_work["specular"]
    is_water = mat_work["is_water"]

    # ══════════════════════════════════════════════════════════
    # 阶段 4：太阳方向与颜色
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.40, "太阳方向")

    # 太阳光线方向（从太阳射向地面）
    sun_dir = s3.sun_to_room_dir(light.az, light.alt)

    # 从墙面点 P 到太阳的方向
    L_to_sun = -sun_dir

    # 太阳颜色
    if sun_color_rgb is None:
        if light.source == "sun":
            sun_color_rgb = astro.sun_color_from_altitude(light.alt)
        elif light.source == "moon":
            sun_color_rgb = np.array([0.62, 0.72, 0.95], dtype=np.float32)
        else:
            sun_color_rgb = np.array([1.0, 1.0, 1.0], dtype=np.float32)

    sun_color_rgb = np.asarray(sun_color_rgb, dtype=np.float32)

    # 太阳辐照度
    if sun_irradiance <= 0.0:
        sun_irradiance = float(light.irradiance)

    config.LOG.param("sun_dir", f"{sun_dir.tolist()}")
    config.LOG.param("sun_color", f"{sun_color_rgb.tolist()}")
    config.LOG.param("sun_irradiance", f"{sun_irradiance:.4f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 5：窗户可见性
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.50, "窗户可见性")
    visible, _ = scene.is_visible_through_window_batch(P, sun_dir)
    visible_f = visible.astype(np.float32)
    visible_ratio = float(visible.mean())
    config.LOG.param("可见性比例", f"{visible_ratio*100:.2f}%")

    # ══════════════════════════════════════════════════════════
    # 阶段 6：漫反射项
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.60, "漫反射")
    N_dot_L = np.sum(normal * L_to_sun[None, None, :], axis=-1)
    N_dot_L = np.maximum(N_dot_L, 0.0) * visible_f

    diffuse = albedo * (sun_color_rgb[None, None, :]
                        * N_dot_L[..., None]
                        * sun_irradiance)

    # ══════════════════════════════════════════════════════════
    # 阶段 7：Cook-Torrance 镜面
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.68, "镜面反射")

    # 视线方向 V（从 P 到相机）
    V = scene.cam_pos[None, None, :] - P
    V_norm = np.linalg.norm(V, axis=-1, keepdims=True)
    V = V / np.maximum(V_norm, 1e-6)

    # 半角向量 H
    Hv = V + L_to_sun[None, None, :]
    H_norm = np.linalg.norm(Hv, axis=-1, keepdims=True)
    Hv = Hv / np.maximum(H_norm, 1e-6)

    # 点积
    N_dot_V = np.maximum(np.sum(normal * V, axis=-1), 0.0)
    N_dot_H = np.maximum(np.sum(normal * Hv, axis=-1), 0.0)

    # Cook-Torrance BRDF
    spec_brdf = _cook_torrance(N_dot_L, N_dot_V, N_dot_H, roughness)

    # 镜面纹理调制
    spec_tex_factor = 1.0 + specular_tex * 0.5

    # 镜面项
    specular_term = (sun_color_rgb[None, None, :]
                     * (spec_brdf * spec_tex_factor)[..., None]
                     * visible_f[..., None]
                     * sun_irradiance)

    # ══════════════════════════════════════════════════════════
    # 阶段 8：水面反射
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.78, "水面反射")
    water_term = _water_reflection(
        P, normal, V, L_to_sun, light, weather, sun_color_rgb, sun_irradiance)

    is_water_3 = is_water[..., None]
    specular_final = np.where(is_water_3, water_term, specular_term)

    # ══════════════════════════════════════════════════════════
    # 阶段 9：环境光
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.86, "环境光")
    ambient_color, ambient_strength = _ambient_terms(light, weather, cfg)
    ambient = albedo * (ambient_color[None, None, :] * ambient_strength)

    # ══════════════════════════════════════════════════════════
    # 阶段 10：合成
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.92, "合成")
    I_traced = diffuse + specular_final + ambient

    # 无效区域用环境光兜底
    I_traced = np.where(valid[..., None], I_traced, ambient)

    I_traced = np.clip(I_traced, 0.0, None).astype(np.float32)

    # ══════════════════════════════════════════════════════════
    # 阶段 11：上采样到原尺寸
    # ══════════════════════════════════════════════════════════
    if work_W != W or work_H != H:
        rep(progress, 0.96, f"上采样到 {W}x{H}")
        I_traced = _upsample_rgb(I_traced, W, H)

    rep(progress, 1.00, "着色完成")

    config.LOG.param("I_traced max", f"{float(I_traced.max()):.4f}")
    config.LOG.param("I_traced mean", f"{float(I_traced.mean()):.4f}")

    return I_traced


# ═══════════════════════════════════════════════════════════════════
# Cook-Torrance BRDF
# ═══════════════════════════════════════════════════════════════════
def _cook_torrance(N_dot_L, N_dot_V, N_dot_H, roughness):
    """
    Cook-Torrance 镜面 BRDF（DFG 三项）。
    D: GGX，G: Smith，F: Schlick（F0 = 0.04）
    """
    # α = roughness²
    a = np.maximum(roughness, 0.03) ** 2
    a2 = a * a

    # D: GGX
    denom_h = N_dot_H ** 2 * (a2 - 1.0) + 1.0
    D = a2 / (math.pi * denom_h ** 2 + 1e-6)

    # G: Smith
    k = a / 2.0
    G1_L = N_dot_L / (N_dot_L * (1.0 - k) + k + 1e-6)
    G1_V = N_dot_V / (N_dot_V * (1.0 - k) + k + 1e-6)
    G = G1_L * G1_V

    # F: Schlick
    F = 0.04 + 0.96 * (1.0 - N_dot_V) ** 5

    # 合成
    denom = 4.0 * N_dot_L * N_dot_V + 1e-6
    brdf = (D * G * F) / denom

    return np.clip(brdf, 0.0, 20.0).astype(np.float32)


# ═══════════════════════════════════════════════════════════════════
# Fresnel（Schlick）
# ═══════════════════════════════════════════════════════════════════
def _fresnel_schlick(cos_theta, F0=0.04):
    """Schlick Fresnel。cos_theta ∈ [0, 1]。"""
    return F0 + (1.0 - F0) * (1.0 - cos_theta) ** 5


# ═══════════════════════════════════════════════════════════════════
# 水面反射
# ═══════════════════════════════════════════════════════════════════
def _water_reflection(P, normal, V, L_to_sun,
                       light, weather, sun_color_rgb, sun_irradiance):
    """
    水面：Fresnel 反射 + 环境采样 + 高光。
    """
    N_dot_V = np.maximum(np.sum(normal * V, axis=-1), 0.0)
    F = _fresnel_schlick(N_dot_V, F0=0.02)

    # 反射方向 R（从 P 出发）
    N_dot_V_c = np.sum(normal * V, axis=-1, keepdims=True)
    R_dir = 2.0 * N_dot_V_c * normal - V
    R_norm = np.linalg.norm(R_dir, axis=-1, keepdims=True)
    R_dir = R_dir / np.maximum(R_norm, 1e-6)

    # 环境采样
    sky_color = np.array([0.55, 0.68, 1.00], dtype=np.float32)
    ground_color = np.array([1.00, 0.85, 0.65], dtype=np.float32)

    r_up = np.clip(R_dir[..., 1], 0.0, 1.0)[..., None]
    env_color = (sky_color[None, None, :] * r_up
                 + ground_color[None, None, :] * (1.0 - r_up))

    env_reflection = env_color * F[..., None] * (0.15 * sun_irradiance)

    # 高光
    Hv = V + L_to_sun[None, None, :]
    H_norm = np.linalg.norm(Hv, axis=-1, keepdims=True)
    Hv = Hv / np.maximum(H_norm, 1e-6)
    N_dot_H = np.maximum(np.sum(normal * Hv, axis=-1), 0.0)
    shininess = 200.0
    spec = N_dot_H ** shininess

    spec_color = sun_color_rgb[None, None, :] * spec[..., None] * sun_irradiance

    return (env_reflection + spec_color).astype(np.float32)


# ═══════════════════════════════════════════════════════════════════
# 环境光
# ═══════════════════════════════════════════════════════════════════
def _ambient_terms(light, weather, cfg):
    """返回 (ambient_color (3,), ambient_strength scalar)。

    天光（天空漫射）强度来自 astro.sky_irradiance，随太阳高度角与云量
    变化；用于修正“白天无直射 = 夜间量级”的缺陷。
    """
    sun_alt = float(getattr(light, "sun_alt", light.alt) or 0.0)
    sky = astro.sky_irradiance(sun_alt, weather.cloud)   # 夜=0，白天>0

    if light.source == "sun":
        sky_c = np.array([0.55, 0.68, 1.00], dtype=np.float32)
        ground = np.array([1.00, 0.85, 0.65], dtype=np.float32)
        mix = 0.6
        color = mix * sky_c + (1.0 - mix) * ground
        strength = max(0.06, sky)
    elif light.source == "twilight":
        color = np.array([0.75, 0.60, 0.55], dtype=np.float32)
        strength = 0.08
    elif light.source == "moon":
        color = np.array([0.55, 0.68, 0.95], dtype=np.float32)
        strength = 0.04
    elif sky > 0.0:
        # 白天但无直射光：墙面完全由天光漫射照亮
        color = astro.sky_color(sun_alt)
        strength = max(0.06, sky)
    else:
        # 真夜间且无直射
        color = np.array([0.50, 0.55, 0.75], dtype=np.float32)
        strength = 0.02

    color = color / max(float(color.mean()), 1e-6)
    from_sky = (light.source == "sun"
                or (light.source == "none" and sky > 0.0))
    if weather.cloud > 50 and not from_sky:
        strength *= (1.0 - 0.4 * (weather.cloud - 50) / 50.0)
    return color, float(strength)


# ═══════════════════════════════════════════════════════════════════
# 材质缩放
# ═══════════════════════════════════════════════════════════════════
def _resize_material(material: Optional[Dict[str, np.ndarray]],
                     work_W: int, work_H: int) -> Dict[str, np.ndarray]:
    """材质 dict 缩放到工作尺寸。若 None → 默认材质。"""
    if material is None:
        return _default_material(work_W, work_H)

    out = {}
    for key in ("albedo", "normal", "roughness", "specular", "is_water"):
        arr = material.get(key)
        if arr is None:
            out[key] = _default_material(work_W, work_H)[key]
            continue

        orig_H, orig_W = arr.shape[:2]
        if orig_H == work_H and orig_W == work_W:
            out[key] = arr
            continue

        if key == "is_water":
            out[key] = utils.resize_np(
                arr.astype(np.float32), work_W, work_H) > 0.5
        else:
            out[key] = utils.resize_np(arr, work_W, work_H)

    return out


def _default_material(work_W: int, work_H: int) -> Dict[str, np.ndarray]:
    """默认材质：白墙 + Lambertian + 朝相机法线。"""
    albedo = np.ones((work_H, work_W, 3), dtype=np.float32)
    normal = np.zeros((work_H, work_W, 3), dtype=np.float32)
    normal[..., 2] = 1.0
    roughness = np.full((work_H, work_W), 0.7, dtype=np.float32)
    specular = np.zeros((work_H, work_W), dtype=np.float32)
    is_water = np.zeros((work_H, work_W), dtype=bool)
    return {
        "albedo": albedo,
        "normal": normal,
        "roughness": roughness,
        "specular": specular,
        "is_water": is_water,
    }


# ═══════════════════════════════════════════════════════════════════
# 上采样（numpy 双线性，避免 PIL.F 兼容性问题）
# ═══════════════════════════════════════════════════════════════════
def _upsample_rgb(arr: np.ndarray, W: int, H: int) -> np.ndarray:
    """
    (h, w, 3) → (H, W, 3) 双线性上采样。
    用 numpy 实现，避免 PIL 兼容性问题。
    """
    h, w = arr.shape[:2]
    if h == H and w == W:
        return arr

    # 目标像素在原图的浮点坐标
    yy = np.linspace(0, h - 1, H, dtype=np.float64)
    xx = np.linspace(0, w - 1, W, dtype=np.float64)
    yy0 = np.floor(yy).astype(np.int32)
    xx0 = np.floor(xx).astype(np.int32)
    yy1 = np.minimum(yy0 + 1, h - 1)
    xx1 = np.minimum(xx0 + 1, w - 1)
    wy = (yy - yy0)[:, None]  # (H, 1)
    wx = (xx - xx0)[None, :]  # (1, W)

    out = np.zeros((H, W, 3), dtype=np.float32)
    for c in range(3):
        a = arr[yy0[:, None], xx0[None, :], c]
        b = arr[yy0[:, None], xx1[None, :], c]
        d = arr[yy1[:, None], xx0[None, :], c]
        e = arr[yy1[:, None], xx1[None, :], c]
        out[..., c] = ((1 - wy) * (1 - wx) * a +
                       (1 - wy) * wx * b +
                       wy * (1 - wx) * d +
                       wy * wx * e)
    return out


# ═══════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════
def _self_test():
    """无材质、无头绪的完整流程测试。"""
    import datetime
    from . import light as light_mod

    W, H = 512, 288

    t = datetime.datetime(2024, 6, 21, 10, 30).astimezone()
    w = astro.WeatherInfo(cloud=0, vis=20000)
    L = light_mod.compute_light(30.58, 114.27, t, w, "right")

    scene = s3.Scene3D()
    scene.set_image_size(W, H)

    I = trace_scene(W, H, L, w, scene, material=None)
    print(f"I_traced shape: {I.shape}")
    print(f"I_traced max:   {I.max():.4f}")
    print(f"I_traced mean:  {I.mean():.4f}")

    center = I[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20]
    print(f"center mean:    {center.mean():.4f}")

    corner = I[:40, :40]
    print(f"corner mean:    {corner.mean():.4f}")


if __name__ == "__main__":
    _self_test()