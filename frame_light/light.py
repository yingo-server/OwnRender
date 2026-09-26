#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 编排

职责：
  1. LightResult 数据类
  2. compute_light() — 串 astro + geometry，返回 LightResult
  3. compute_scene_lights() — 转发给 scene
  4. 分级 / 描述 / 提示词 / 底图诊断 / 结果预测

本文件是编排层，可 import 本框架全部小文件。
只 import config + utils + astro + geometry + scene。
"""
import math
from typing import Tuple, Optional, Dict, Any

import numpy as np
from PIL import Image

import config
from . import utils
from . import astro
from . import geometry
from . import scene
from . import atmosphere


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════
class LightResult:
    """光照计算结果（数值，不含像素）。"""
    def __init__(self):
        self.source = "none"      # sun / moon / twilight / none
        self.az = 0.0
        self.alt = 0.0
        self.irradiance = 0.0
        self.color = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        self.ambient_irradiance = 0.0
        self.ambient_color = np.array([0.1, 0.1, 0.15], dtype=np.float32)
        self.sun_alt = 0.0

        # 光斑几何
        self.patch_center_x = 0.5
        self.patch_center_y = 0.5
        self.patch_width = 0.4
        self.patch_height = 0.5
        self.patch_shear_x = 0.0
        self.patch_shear_y = 0.0
        self.penumbra_ratio = 0.02

        # 阴影
        self.shadow_dx = 0.0
        self.shadow_dy = 0.0

        # 元数据
        self.is_night = False
        self.description = ""
        self.h_word = "无"
        self.v_word = "无"
        self.visibility_reason = ""

        # ── 天气光质（由 config.weather_look() 填入）──
        # 天气不只是"亮度旋钮"：它决定光的硬度、湿面、空气感、色偏…
        self.weather_type = "clear"
        self.hardness = 1.0        # 直射硬度（软=光斑边界更糊）
        self.contrast = 1.0        # 输出对比度
        self.saturation = 1.0      # 饱和度
        self.cool = 0.0            # 冷色偏
        self.wet = 0.0             # 湿面程度
        self.bounce = 0.06         # 地面反弹
        self.airlight = 0.01       # 空气光幕

        # ── 曝光 / 天气动态 ──
        self.illuminance = 0.0     # 总照度（自适应曝光的输入）
        self.direct_open = 1.0     # 保留字段（兼容）
        self.cloud_eff = 0.0
        self.precip_eff = 0.0
        self.exposure_ev = 1.0     # 实际使用的曝光倍率
        self.burst = 0.0           # 阵雨强度（0=云开，1=雨最急）
        self.ground_state = "dry"  # 地面状态（snow/wet/dry）


# ═══════════════════════════════════════════════════════════════════
# 物理可达性
# ═══════════════════════════════════════════════════════════════════
def _relative_az(source_az, win_side):
    win_az = config.WINDOW_SIDE_AZ.get(win_side, 90)
    rel = source_az - win_az
    while rel > 180: rel -= 360
    while rel < -180: rel += 360
    return rel


def _sun_visibility(sun_alt, sun_az, win_side, cloud, vis_m=20000.0):
    if sun_alt <= -6:
        return False, f"太阳在地平线下（alt={sun_alt:.1f}°）"
    if sun_alt < 0:
        return True, "暮光阶段"
    az_rel = _relative_az(sun_az, win_side)
    if abs(az_rel) > 100:
        win_az_dbg = config.WINDOW_SIDE_AZ.get(win_side, 90)
        return False, (f"太阳在窗户背面（相对方位 {az_rel:+.0f}°，"
                       f"窗户朝向 {win_side}={win_az_dbg:.0f}°）")
    # 云量不用 95% 一刀切：厚云正午仍有约 10% 直射/散射光，
    # 一刀切会把白天渲成黑图。这里改为看"直射辐照度是否可忽略"。
    irr = astro.solar_irradiance(sun_alt, cloud, vis_m)
    if irr < 0.0005:
        return False, f"云量 {cloud:.0f}%，直射光极弱（{irr:.4f}）"
    return True, f"阳光可达（云量 {cloud:.0f}%，直射 {irr:.3f}）"


def _moon_visibility(moon_alt, moon_az, phase, cloud, win_side):
    if moon_alt <= 0:
        return False, f"月亮在地平线下（alt={moon_alt:.1f}°）"
    if moon_alt < 5:
        return False, f"月亮高度角仅 {moon_alt:.1f}°，被地平线/建筑遮挡"
    az_rel = _relative_az(moon_az, win_side)
    if abs(az_rel) > 100:
        win_az_dbg = config.WINDOW_SIDE_AZ.get(win_side, 90)
        return False, (f"月亮在窗户背面（相对方位 {az_rel:+.0f}°，"
                       f"窗户朝向 {win_side}={win_az_dbg:.0f}°）")
    bf = astro.moon_brightness_factor(phase)
    if bf < 0.15:
        return False, (f"月相 {phase:.2f}，接近新月，"
                       f"月光极弱（brightness={bf:.2f}）")
    if astro.moon_irradiance(moon_alt, phase, cloud) < 0.0005:
        return False, f"云量 {cloud:.0f}%，月光极弱"
    return True, "月光可达"


# ═══════════════════════════════════════════════════════════════════
# 主入口：compute_light
# ═══════════════════════════════════════════════════════════════════
def _compute_light_impl(lat, lon, dt, weather,
                        window_orientation="right",
                        shadow_length="auto") -> LightResult:
    """从时间/位置/天气/窗户朝向算出光照物理参数（不含曝光/天气光质）。"""
    win = config.WINDOW_ORIENTATION_ALIAS.get(
        str(window_orientation).lower(), str(window_orientation).lower())
    if win not in config.WINDOW_ORIENTATIONS:
        win = "right"

    L = LightResult()
    sun_az, sun_alt = astro.sun_position(lat, lon, dt)
    moon_az, moon_alt = astro.moon_position(lat, lon, dt)
    phase = astro.moon_phase(dt)
    L.sun_alt = sun_alt

    config.LOG.param("UTC",
                     utils.to_utc_naive(dt).strftime("%Y-%m-%d %H:%M:%S"))
    config.LOG.param("太阳", f"az={sun_az:.2f} alt={sun_alt:.2f}")
    config.LOG.param("月亮",
                     f"az={moon_az:.2f} alt={moon_alt:.2f} phase={phase:.3f}")
    config.LOG.param("窗户", win)
    config.LOG.param("天气", f"cloud={weather.cloud}% vis={weather.vis}m")

    # ── 太阳优先 ──
    sun_vis, sun_reason = _sun_visibility(sun_alt, sun_az, win,
                                         weather.cloud, weather.vis)
    if sun_vis:
        L.is_night = (sun_alt <= 0)
        if sun_alt > 0:
            L.source = "sun"
            L.az, L.alt = sun_az, sun_alt
            L.irradiance = astro.solar_irradiance(sun_alt, weather.cloud,
                                                   weather.vis)
            L.color = astro.sun_color_from_altitude(sun_alt) * weather.color_shift
            # 天光漫射：即使有直射光斑，墙面整体仍被天空照亮
            L.ambient_irradiance = astro.sky_irradiance(sun_alt,
                                                        weather.cloud)
            L.ambient_color = astro.sky_color(sun_alt)
            L.description = f"太阳 {sun_alt:+.1f}° 辐照 {L.irradiance:.3f}"
        else:
            L.source = "twilight"
            L.az, L.alt = sun_az, sun_alt
            L.irradiance = 0.0
            L.color = astro.twilight_color(sun_alt)
            scatter = max(0.0, min(1.0, (0 - sun_alt) / 6.0))
            L.ambient_irradiance = 0.06 * scatter
            L.ambient_color = np.array([0.15, 0.20, 0.40], dtype=np.float32)
            L.description = (f"暮光 {sun_alt:+.1f}° "
                             f"散射 {L.ambient_irradiance:.4f}")

        L.h_word = utils.az_to_h_word(sun_az)
        L.v_word = utils.alt_to_v_word(sun_alt)
        L.visibility_reason = sun_reason

        if L.irradiance > 0.0005:
            geometry.compute_patch_geometry(L, win)
            geometry.compute_penumbra(L, weather)
            L.shadow_dx, L.shadow_dy = geometry.compute_shadow(
                L.alt, L.az, shadow_length)
        return L

    # ── 月亮 ──
    moon_vis, moon_reason = _moon_visibility(
        moon_alt, moon_az, phase, weather.cloud, win)
    if moon_vis:
        L.is_night = True
        L.source = "moon"
        L.az, L.alt = moon_az, moon_alt
        L.irradiance = astro.moon_irradiance(moon_alt, phase, weather.cloud)
        L.color = np.array([0.62, 0.72, 0.95], dtype=np.float32)
        L.h_word = utils.az_to_h_word(moon_az)
        L.v_word = utils.alt_to_v_word(moon_alt)
        L.description = (f"月亮 {moon_alt:+.1f}° 月相 {phase:.2f} "
                         f"辐照 {L.irradiance:.4f}")
        L.visibility_reason = moon_reason

        if L.irradiance > 0.0005:
            geometry.compute_patch_geometry(L, win)
            geometry.compute_penumbra(L, weather)
            L.shadow_dx, L.shadow_dy = geometry.compute_shadow(
                L.alt, L.az, shadow_length)
        return L

    # ── 无直射光（可能是白天：太阳被窗户背面挡住的漫射照明）──
    L.is_night = (sun_alt <= 0)
    L.source = "none"
    L.irradiance = 0.0
    # 白天：天光漫射；夜间：夜空辉光 + 月光散射（随时间/月相/云量变化）
    _sky = astro.sky_irradiance(sun_alt, weather.cloud)
    if _sky > 0.0:
        L.ambient_irradiance = _sky
        L.ambient_color = astro.sky_color(sun_alt)
    else:
        _night = astro.night_sky_irradiance(moon_alt, phase, weather.cloud)
        L.ambient_irradiance = _night
        L.ambient_color = np.array([0.30, 0.36, 0.58], dtype=np.float32)
    L.description = f"无直射光（太阳：{sun_reason}；月亮：{moon_reason}）"
    L.visibility_reason = f"太阳:{sun_reason} / 月亮:{moon_reason}"
    config.LOG.info(f"无直射光：{L.visibility_reason}")
    return L


# ═══════════════════════════════════════════════════════════════════
# 天气光质 / 曝光适应
# ═══════════════════════════════════════════════════════════════════
def effective_weather_kind(weather) -> str:
    """归一化天气类型。优先级：显式指定 > WMO code > 云/水/视推导。

    为什么 code 要排在推导前面：API 只给了 precip/temp/vis/cloud，
    推导出来永远是 "rain"；而 WMO code=95 其实是**雷阵雨**、80~82 是**阵雨**。
    旧实现完全没用 code，所以"雷阵雨"被当成"一直下的小雨"渲染。
    """
    kinds = set(getattr(config, "WEATHER_TYPES", ())) - {"auto"}
    f = str(getattr(weather, "forced_type", "") or "").lower()
    if f and f != "auto" and f in kinds:
        return f
    code_kind = astro.categorize_code(getattr(weather, "code", None))
    if code_kind:
        return code_kind
    t = str(getattr(weather, "weather_type", "") or "").lower()
    return t if t in kinds else "cloudy"


def compute_light(lat, lon, dt, weather,
                  window_orientation="right",
                  shadow_length="auto") -> LightResult:
    """计算光照 —— 在物理内核之外补上**之前缺的三层处理**：

      1. 阵雨/雷阵雨的间歇性（云开云合 → 太阳时隐时现）
      2. 天气光质：**全部由物理量推导**（见 frame_light/atmosphere.py）
         · 直射/漫射分离：覆盖加权云透过率 + 云修正因子 + 能量守恒
         · 地面反弹：雪/湿/干的反照率
         · 湿面：降水率 → 水膜覆盖率
         · 空气光：能见度 → Koschmieder β × 室内光程
      3. 视觉适应曝光（Stevens 幂律）：阴雨天不再"按比例变暗"
    """
    kind = effective_weather_kind(weather)

    # ── 阵雨/雷阵雨：云在开合 ──
    burst = 0.0
    if kind in ("shower", "thunder") and dt is not None:
        cloud_eff, precip_eff, burst = astro.shower_dynamics(
            dt, weather.cloud, weather.precip, kind)
        weather.cloud = cloud_eff
        weather.precip = precip_eff
    if getattr(weather, "forced_type", None) in (None, "", "auto"):
        try:
            weather.forced_type = kind
        except Exception:                       # noqa: BLE001
            pass

    L = _compute_light_impl(lat, lon, dt, weather,
                            window_orientation, shadow_length)

    # ── 物理推导：晴空量 → 当前天气的 (直射, 漫射) 与各项光质 ──
    sun_alt = float(getattr(L, "sun_alt", L.alt) or 0.0)
    scene_cfg = config.get_lighting().get("scene", {}) or {}
    path_m = float(scene_cfg.get("room_d_m", 4.0))          # 室内光程（真实几何）
    clear_diffuse = astro.sky_irradiance(sun_alt, 0.0)      # 晴空天光
    clear_beam = astro.solar_irradiance(sun_alt, 0.0, 20000.0)

    ph = atmosphere.derive(
        cloud=float(getattr(weather, "cloud", 0.0)),
        precip=float(getattr(weather, "precip", 0.0)),
        temp=float(getattr(weather, "temp", 20.0)),
        vis_m=float(getattr(weather, "vis", 20000.0)),
        humidity=float(getattr(weather, "humidity", 50.0)),
        sun_alt=sun_alt, path_m=path_m,
        clear_beam=clear_beam, clear_diffuse=clear_diffuse)

    # 夜间没有太阳：走夜空辉光/月光分支，只用地面反弹修正环境光
    if L.source == "sun" and sun_alt > 0.0:
        L.irradiance = ph["beam"]
        L.ambient_irradiance = ph["diffuse"]
    elif L.source == "none" and sun_alt > 0.0:
        # 白天但太阳不在窗那侧：直射为 0（被墙挡），漫射照旧
        L.ambient_irradiance = ph["diffuse"]
    else:
        # 夜/暮光：月光散射 + 夜空辉光已在 _compute_light_impl 里算好
        pass

    L.weather_type = kind
    L.hardness = float(ph["hardness"])
    L.contrast = float(ph["contrast"])
    L.saturation = float(ph["saturation"])
    L.cool = 0.0                      # 色偏由 astro.weather_color_shift 负责（已有物理）
    L.wet = float(ph["wet"])
    L.bounce = float(ph["bounce"])
    L.airlight = float(ph["airlight"])
    L.ground_state = str(ph["ground"])
    L.burst = float(burst)
    L.cloud_eff = float(weather.cloud)
    L.precip_eff = float(weather.precip)

    L.illuminance = float(max(0.0, L.irradiance) + max(0.0, L.ambient_irradiance))
    L.exposure_ev = atmosphere.eye_exposure_ev(L.illuminance, 1.0, sun_alt)

    config.LOG.param("直射/漫射",
                     f"{L.irradiance:.4f} / {L.ambient_irradiance:.4f} "
                     f"（硬度 {L.hardness:.2f}）")
    config.LOG.param("光质推导",
                     f"湿面 {L.wet:.2f} 地面 {L.ground_state} "
                     f"反弹 {L.bounce:.2f} 空气光 {L.airlight:.4f} "
                     f"对比 {L.contrast:.3f} 饱和 {L.saturation:.3f}")
    config.LOG.param("照度/曝光",
                     f"E={L.illuminance:.4f} EV={L.exposure_ev:.3f}"
                     + (f" burst={burst:.2f}" if burst else ""))
    return L


# ═══════════════════════════════════════════════════════════════════
# 转发：4 层光照
# ═══════════════════════════════════════════════════════════════════
def compute_scene_lights(light, weather, R_mean, cfg=None) -> dict:
    """转发到 scene.compute_scene_lights。"""
    return scene.compute_scene_lights(light, weather, R_mean, cfg)


# ═══════════════════════════════════════════════════════════════════
# 分级
# ═══════════════════════════════════════════════════════════════════
def classify_light(dt, alt):
    hour = dt.hour
    if alt <= 0: base = 0
    elif alt < 5: base = 1
    elif alt < 10: base = 2
    elif alt < 15: base = 3
    elif alt < 20: base = 4
    elif alt < 30: base = 5
    elif alt < 40: base = 6
    elif alt < 50: base = 7
    elif alt < 60: base = 8
    elif alt < 70: base = 9
    else: base = 10
    if 5 <= hour < 7:    return max(3, min(base, 6))
    elif 7 <= hour < 9:  return max(4, min(base, 7))
    elif 9 <= hour < 11: return max(5, min(base, 8))
    elif 11 <= hour < 13:return max(6, min(base, 9))
    elif 13 <= hour < 15:return max(5, min(base, 9))
    elif 15 <= hour < 17:return max(4, min(base, 10))
    elif 17 <= hour < 19:return max(3, min(base, 10))
    elif 19 <= hour < 21:return 11
    elif 21 <= hour < 23:return 12
    else: return 0


def classify_light_auto(dt, light) -> int:
    if light.source == "moon":
        hour = dt.hour
        if hour >= 21 or hour < 5: return 12
        if hour >= 18 or hour < 7: return 11
        return 12
    if light.source == "none":
        hour = dt.hour
        return 11 if 18 <= hour < 21 else 12
    return classify_light(dt, light.alt)


# ═══════════════════════════════════════════════════════════════════
# 描述 / 提示词
# ═══════════════════════════════════════════════════════════════════
def describe_single_window_light(light_result) -> str:
    irr = light_result.irradiance
    if irr < 0.005:
        intensity = "none"
    elif light_result.source == "twilight":
        intensity = "dim"
    elif irr < 0.15:
        intensity = "dim"
    elif irr < 0.45:
        intensity = "soft"
    else:
        intensity = "strong"

    if intensity == "none":
        return "画面中没有任何直射光，只有均匀的暗环境光，墙面整体处于阴影中。"

    sw = {"strong": "清晰锐利的", "soft": "清晰柔和的",
          "dim": "柔和模糊的"}.get(intensity, "柔和的")
    h_word = getattr(light_result, "h_word", "无")
    v_word = getattr(light_result, "v_word", "无")
    pos_word = "画面中" if h_word == "无" else f"画面{h_word}{v_word}处"

    if light_result.source == "moon":
        return (f"画面中有一束{sw}矩形网格状光斑落在墙面{pos_word}，"
                f"光斑为冷蓝白色，边界柔和，光照方向明确。")
    return (f"画面中有一束{sw}矩形网格状光斑落在墙面{pos_word}，"
            f"光斑边界清晰，光照方向明确。")


def build_base_prompt(aspect, light_lv, wall_desc, light_result,
                      prompts=None, grid_rows=2, grid_cols=2):
    prompts = prompts or config.get_prompts()
    scene_p = prompts.get("scene_profiles", {}).get(
        str(light_lv), prompts.get("scene_profiles", {}).get("7", ""))
    vision = prompts.get("vision", {}).get(
        aspect, prompts.get("vision", {}).get("16:9", ""))
    style = prompts.get("style_suffix", "")
    no_entities      = prompts.get("no_entities", "")
    no_window        = prompts.get("no_window", "")
    no_window_strong = prompts.get("no_window_strong", "")
    light_hint       = prompts.get("window_light_hint", "")
    light_desc = describe_single_window_light(light_result)
    return (
        f"场景与背景：{wall_desc}。"
        f"{no_entities}{no_window}\n"
        f"光照与氛围：{light_desc} {scene_p}"
        f"{light_hint}{no_window_strong}\n"
        f"构图与风格：{vision} {style}"
    )


# ═══════════════════════════════════════════════════════════════════
# 底图诊断
# ═══════════════════════════════════════════════════════════════════
def analyze_wall(wall_img: Image.Image) -> Dict[str, float]:
    h, w = wall_img.size[1], wall_img.size[0]
    if max(h, w) > 512:
        scale = 512 / max(h, w)
        img_s = wall_img.convert("L").resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            config.RESAMPLE_BILINEAR)
        arr = np.asarray(img_s, dtype=np.float32) / 255.0
    else:
        arr = np.asarray(wall_img.convert("L"), dtype=np.float32) / 255.0
    flat = arr.flatten()
    return {
        "lum_mean": float(arr.mean()),
        "lum_std":  float(arr.std()),
        "lum_p10":  float(np.percentile(flat, 10)),
        "lum_p90":  float(np.percentile(flat, 90)),
    }


def diagnose_wall(wall_img: Image.Image) -> Tuple[str, str]:
    a = analyze_wall(wall_img)
    lm = a["lum_mean"]
    if lm < 0.03:
        return "too_dark", f"底图极暗（亮度 {lm:.3f}），光斑对比可能不足"
    if lm < 0.08:
        return "dark", f"底图偏暗（亮度 {lm:.3f}），光斑会更突出"
    if lm > 0.75:
        return "bright", f"底图偏亮（亮度 {lm:.3f}），光斑对比会受限"
    return "ok", f"底图亮度 {lm:.3f}，适合渲染"


# ═══════════════════════════════════════════════════════════════════
# 结果预测
# ═══════════════════════════════════════════════════════════════════
def predict_result(light: LightResult, weather,
                   wall_img: Optional[Image.Image] = None,
                   grid_rows: int = 3, grid_cols: int = 2) -> Dict[str, Any]:
    warnings = []

    if wall_img is not None:
        wall_level, wall_msg = diagnose_wall(wall_img)
        if wall_level in ("too_dark", "bright"):
            warnings.append(wall_msg)

    if light.source == "none":
        warnings.append(f"当前无任何直射光：{light.visibility_reason}")
        warnings.append("画面将只有微弱环境光，无光斑")
        return {
            "verdict": "warn",
            "summary": "无直射光，仅渲染暗环境",
            "warnings": warnings,
            "patch_expected": "无光斑",
            "energy": "极弱",
        }

    irr = light.irradiance
    if irr > 0.5:
        patch_expected = "非常清晰、明亮"; energy = "强"
    elif irr > 0.3:
        patch_expected = "清晰可见"; energy = "中"
    elif irr > 0.1:
        patch_expected = "可见，略柔和"; energy = "弱"
    elif irr > 0.03:
        patch_expected = "微弱，需要仔细观察"; energy = "极弱"
        warnings.append(f"辐照度 {irr:.3f} 很低，光斑可能不明显")
    else:
        patch_expected = "几乎不可见"; energy = "近似无"
        warnings.append(f"辐照度 {irr:.3f} 极低，光斑几乎不可见")

    wt = weather.weather_type
    if wt == "overcast":
        warnings.append("阴天散射光，光斑边界会非常模糊")
    elif wt == "rain":
        warnings.append("雨天，会叠加水痕效果")
    elif wt == "snow":
        warnings.append("雪天，会叠加雪花亮点")
    elif wt == "haze":
        warnings.append("雾霾，光斑会明显模糊")
    if light.is_night and light.source == "moon":
        warnings.append("夜间月光，光斑呈冷蓝白色")

    if len(warnings) == 0:
        verdict = "good"
    elif any("极暗" in w or "无任何直射" in w or "极低" in w for w in warnings):
        verdict = "warn"
    else:
        verdict = "good" if len(warnings) <= 1 else "warn"

    return {
        "verdict": verdict,
        "summary": (f"光源 {light.source} / 强度 {energy} / "
                    f"光斑 {patch_expected}"),
        "warnings": warnings,
        "patch_expected": patch_expected,
        "energy": energy,
    }