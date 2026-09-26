#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — 编排（光线追踪版）

职责：
  1. generate_lit_wall() — 编排 Retinex → Material → Raytrace → ACES → 相机
  2. render_fusion() — 转发 text.fuse

架构：
  frame_render 不 import frame_light（避免循环）
  通过延迟 import 使用 frame_light.scene3d / raytrace / astro

本文件是编排层，可 import 本框架全部小文件 + 跨框架。
"""
import time
from typing import Tuple, Dict, Any, Optional

import numpy as np
from PIL import Image

import config
from . import utils
from . import retinex
from . import material
from . import compose
from . import text as text_render


# ═══════════════════════════════════════════════════════════════════
# 光照底图生成（光线追踪版）
# ═══════════════════════════════════════════════════════════════════
def generate_lit_wall(wall_img: Image.Image,
                      light,
                      weather,
                      window_orientation="right",
                      window_scale=0.65,
                      grid_rows=3, grid_cols=2,
                      grid_frame_ratio=0.18,
                      progress=None) -> Tuple[Image.Image, Dict[str, Any]]:
    """
    光照底图生成（光线追踪版）。

    流程：
      1. Retinex 分解 → R_clean
      2. PBR 五通道材质提取
      3. 3D 场景 + 光线追踪 → I_traced（线性）
      4. ACES tone mapping
      5. 相机效果（渐晕 / 阴影色偏 / CMOS）
      6. 编码为 sRGB PNG
    """
    config.LOG.section("算法光照生成（光线追踪）")
    cfg = config.get_lighting()
    t_all = time.time()

    W, H = wall_img.size

    if progress is not None:
        progress.set_stages([
            "Retinex 分解",
            "材质提取",
            "光线追踪",
            "ACES 映射",
            "相机效果",
            "编码保存",
        ])
        progress.set_stage(0)
        progress.set_progress(0.0)

    # ══════════════════════════════════════════════════════════
    # 阶段 1：Retinex 分解
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.log("进入 Retinex 分解")
    t0 = time.time()
    wall_srgb = np.asarray(wall_img, dtype=np.float32) / 255.0
    wall_lin = utils.srgb_to_linear(wall_srgb)
    config.LOG.timing("反 sRGB", t0)

    t0 = time.time()
    R_clean, S_gray, stats = retinex.decompose_albedo(wall_lin, cfg,
                                                        progress=progress)
    config.LOG.timing("Retinex 分解", t0)
    config.LOG.param("albedo_mean", f"{stats['albedo_mean']:.3f}")
    config.LOG.param("albedo_std", f"{stats['albedo_std']:.3f}")
    config.LOG.param("工作尺寸", stats.get("work_size", "?"))

    R_mean = float(stats.get("albedo_mean", 0.3))

    if progress is not None:
        progress.log(f"Retinex 完成 · R_mean={R_mean:.4f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 2：PBR 五通道材质提取
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.set_stage(1)
        progress.set_progress(0.0)
        progress.log("进入材质提取")

    t0 = time.time()
    mat_obj = material.extract_material(R_clean, cfg, progress=progress)
    config.LOG.timing("材质提取", t0)

    mat_dict = {
        "albedo": mat_obj.albedo,
        "normal": mat_obj.normal,
        "roughness": mat_obj.roughness,
        "specular": mat_obj.specular,
        "is_water": mat_obj.is_water,
    }
    mat_stats = mat_obj.stats()
    config.LOG.param("材质-均值", f"{mat_stats['albedo_mean']:.3f}")
    config.LOG.param("水面比例", f"{mat_stats['water_ratio']*100:.2f}%")

    # ══════════════════════════════════════════════════════════
    # 阶段 3：3D 场景 + 光线追踪
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.set_stage(2)
        progress.set_progress(0.0)
        progress.log("进入光线追踪")

    # 延迟 import frame_light（避免循环依赖）
    from frame_light import scene3d as s3
    from frame_light import raytrace
    from frame_light import astro

    # 构造场景
    scene_cfg = dict(cfg.get("scene", {}))
    scene_cfg["window_side"] = window_orientation
    base_win_w = float(scene_cfg.get("window_w_m", 1.2))
    base_win_h = float(scene_cfg.get("window_h_m", 1.5))
    scene_cfg["window_w_m"] = base_win_w * float(window_scale) / 0.65
    scene_cfg["window_h_m"] = base_win_h * float(window_scale) / 0.65
    # ★ 注入窗格参数
    scene_cfg["grid_rows"] = int(grid_rows)
    scene_cfg["grid_cols"] = int(grid_cols)
    scene_cfg["grid_frame_ratio"] = float(grid_frame_ratio)

    scene = s3.Scene3D(scene_cfg)
    # 不在这里设置 set_image_size，由 raytrace 内部统一处理

    config.LOG.param("场景-窗户",
                     f"{scene_cfg['window_w_m']:.2f} x "
                     f"{scene_cfg['window_h_m']:.2f} m")
    config.LOG.param("场景-窗格",
                     f"{scene_cfg['grid_rows']}x{scene_cfg['grid_cols']} "
                     f"frame={scene_cfg['grid_frame_ratio']:.2f}")
    config.LOG.param("场景-相机", f"{scene.cam_pos.tolist()}")

    # 太阳颜色（分波长）
    if light.source == "sun":
        sun_rgb = astro.solar_irradiance_rgb(
            light.alt, weather.cloud, weather.vis)
    elif light.source == "moon":
        sun_rgb = astro.moon_color_rgb(light.alt)
    else:
        sun_rgb = np.array([1.0, 1.0, 1.0], dtype=np.float32)

    config.LOG.param("太阳-分波长", f"{sun_rgb.tolist()}")
    config.LOG.param("太阳-辐照度", f"{light.irradiance:.4f}")

    t0 = time.time()
    I_traced = raytrace.trace_scene(
        W, H, light, weather, scene,
        material=mat_dict,
        sun_color_rgb=sun_rgb,
        sun_irradiance=light.irradiance,
        progress=progress)
    config.LOG.timing("光线追踪", t0)
    config.LOG.param("I_traced max", f"{float(I_traced.max()):.4f}")
    config.LOG.param("I_traced mean", f"{float(I_traced.mean()):.4f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 4：ACES tone mapping
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.set_stage(3)
        progress.set_progress(0.0)
        progress.log("进入 ACES 映射")

    t0 = time.time()
    aces_gain = float(cfg.get("aces_gain", 1.25))
    # ── 曝光适应（必须在 ACES 之前，线性域）──────────────────────────
    # 没有这一步：阴雨天照度只有晴天的 ~1/3，画面就直接是 1/3 亮 → "阴暗"。
    ev = float(getattr(light, "exposure_ev", 1.0) or 1.0)
    if abs(ev - 1.0) > 1e-3:
        I_traced = I_traced * ev
        config.LOG.param("曝光适应",
                         f"EV={ev:.3f}（照度 E={float(getattr(light, 'illuminance', 0.0)):.4f}）")
    I_out = utils.aces_tonemap_with_gain(I_traced, gain=aces_gain)
    config.LOG.timing("ACES", t0)
    config.LOG.param("I_out max", f"{float(I_out.max()):.4f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 5：相机效果
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.set_stage(4)
        progress.set_progress(0.0)
        progress.log("进入相机效果")

    t0 = time.time()
    I_out = _apply_camera_effects(I_out, light, weather, cfg,
                                    progress=progress)
    config.LOG.timing("相机效果", t0)

    # ══════════════════════════════════════════════════════════
    # 阶段 5.5：画面微调（天气光质 + 用户曝光/饱和度）
    # ══════════════════════════════════════════════════════════
    ex = config.VISUAL_EXPOSURE
    sat = config.VISUAL_SATURATION
    if ex is None:
        ex = float(config._defaults_or("visual_exposure", 1.0))
    if sat is None:
        sat = float(config._defaults_or("visual_saturation", 1.0))

    # 天气光质：对比度 / 饱和度 / 冷色偏（sRGB 域）+ 用户曝光（线性域）
    I_out = compose.apply_look(I_out, light, exposure=ex, saturation=sat)
    if (abs(float(getattr(light, "contrast", 1.0)) - 1.0) > 1e-3
            or abs(float(getattr(light, "saturation", 1.0)) - 1.0) > 1e-3
            or float(getattr(light, "cool", 0.0) or 0.0) > 1e-4):
        config.LOG.param("天气光质后处理",
                         f"对比={float(getattr(light, 'contrast', 1.0)):.2f} "
                         f"饱和={float(getattr(light, 'saturation', 1.0)):.2f} "
                         f"冷偏={float(getattr(light, 'cool', 0.0)):.2f}")
    I_out = np.clip(I_out, 0.0, None)

    # ══════════════════════════════════════════════════════════
    # 阶段 6：编码
    # ══════════════════════════════════════════════════════════
    if progress is not None:
        progress.set_stage(5)
        progress.set_progress(0.0)
        progress.log("进入编码保存")

    lit_img = compose.encode_srgb(I_out)

    if progress is not None:
        progress.set_progress(1.0)
        progress.finish()

    # meta
    meta = {
        "retinex": stats,
        "material_stats": mat_stats,
        "material_map": mat_obj.albedo.mean(axis=2),
        "material_map_rgb": mat_obj.albedo,
        "normal_map": mat_obj.normal,
        "roughness_map": mat_obj.roughness,
        "water_mask": mat_obj.is_water,
        "R_mean": R_mean,
        "I_traced_max": float(I_traced.max()),
        "I_traced_mean": float(I_traced.mean()),
        "I_out_max": float(I_out.max()),
        "sun_color_rgb": sun_rgb.tolist(),
        "sun_irradiance": float(light.irradiance),
    }

    config.LOG.timing("全流程", t_all)
    return lit_img, meta


# ═══════════════════════════════════════════════════════════════════
# 相机效果
# ═══════════════════════════════════════════════════════════════════
def _apply_camera_effects(I_out: np.ndarray,
                           light,
                           weather,
                           cfg: dict,
                           progress=None) -> np.ndarray:
    """
    相机效果：
      1. 阴影色偏（暗部偏蓝）
      2. 镜头渐晕
      3. CMOS 响应曲线
    """
    rep = utils.report
    H, W = I_out.shape[:2]

    # ── 1. 阴影色偏 ──
    shadow_blue = float(cfg.get("shadow_blue_tint", 0.06))
    if shadow_blue > 0:
        rep(progress, 0.30, "阴影色偏")
        lum = I_out.mean(axis=2, keepdims=True)
        weight = np.clip(1.0 - lum * 2.0, 0, 1)
        blue_tint = np.array([0.0, 0.05, 0.10], dtype=np.float32)
        I_out = I_out + weight * blue_tint[None, None, :] * shadow_blue

    # ── 2. 镜头渐晕 ──
    vig = float(cfg.get("vignette_strength", 0.15))
    if vig > 0:
        rep(progress, 0.55, "镜头渐晕")
        yy, xx = np.mgrid[0:H, 0:W]
        cx, cy = W / 2.0, H / 2.0
        max_dist = np.sqrt(cx ** 2 + cy ** 2)
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_dist
        vignette = 1.0 - vig * dist ** 2
        I_out = I_out * vignette[..., None]

    # ── 3. CMOS 响应 ──
    sensor = float(cfg.get("sensor_curve_strength", 0.05))
    if sensor > 0:
        rep(progress, 0.80, "CMOS 响应")
        I_out = I_out * (1.0 + sensor * (1.0 - np.clip(I_out, 0, 1)))

    I_out = np.clip(I_out, 0.0, 1.0)
    rep(progress, 1.00, "相机效果完成")
    return I_out


# ═══════════════════════════════════════════════════════════════════
# 文字叠字（转发）
# ═══════════════════════════════════════════════════════════════════
def render_fusion(image_path, text, font_path,
                  ssaa=8, font_ratio=0.18, seed=None,
                  render_params=None, font_pos=None, light=None,
                  progress=None, stage_offset=0,
                  material_map=None):
    """转发到 text.fuse。"""
    return text_render.fuse(
        image_path, text, font_path,
        ssaa=ssaa, font_ratio=font_ratio, seed=seed,
        render_params=render_params, font_pos=font_pos, light=light,
        progress=progress, stage_offset=stage_offset,
        material_map=material_map)