#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 天文 + 物理 + 环境数据获取

职责：
  1. 天文位置（太阳/月亮/月相）
  2. 大气物理（Beer-Lambert + Kasten-Young）
  3. 分波长太阳辐照度（Rayleigh + Mie）
  4. 黑体辐射色温
  5. 天气数据结构与 API 获取（纯数据，无交互）
  6. NTP 查询（纯数据）
  7. 地理定位查询（纯数据）

不 import 本框架其他文件。
只 import config + utils（本框架）+ 标准库 + requests。
"""
import math
import os
import socket
import struct
import sys
import datetime
import shutil
import subprocess
import json
import re
import time
from typing import Optional
import numpy as np
import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 天文：太阳 / 月亮
# ═══════════════════════════════════════════════════════════════════
def _jd_from_utc(dt_utc: datetime.datetime) -> float:
    y, mo, d = dt_utc.year, dt_utc.month, dt_utc.day
    hh = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    if mo <= 2:
        y -= 1
        mo += 12
    a = y // 100
    b = 2 - a + a // 4
    return (int(365.25 * (y + 4716)) + int(30.6001 * (mo + 1)) +
            d + b - 1524.5 + hh / 24.0)


def sun_position(lat, lon, dt):
    """返回 (方位角°, 高度角°)。"""
    dt_utc = utils.to_utc_naive(dt)
    jd = _jd_from_utc(dt_utc)
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians((L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.0000004 * n)
    alpha = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    delta = math.asin(math.sin(eps) * math.sin(lam))
    hh = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    gmst = (6.697375 + 0.0657098242 * n + hh) % 24
    lmst = (gmst * 15 + lon) % 360
    H = math.radians(lmst - math.degrees(alpha))
    phi = math.radians(lat)
    alt = math.asin(math.sin(phi) * math.sin(delta) +
                    math.cos(phi) * math.cos(delta) * math.cos(H))
    az = math.atan2(-math.cos(delta) * math.sin(H),
                    math.sin(delta) * math.cos(phi) -
                    math.cos(delta) * math.sin(phi) * math.cos(H))
    return math.degrees(az) % 360, math.degrees(alt)


def moon_position(lat, lon, dt):
    """返回 (方位角°, 高度角°)。"""
    dt_utc = utils.to_utc_naive(dt)
    jd = _jd_from_utc(dt_utc)
    n = jd - 2451545.0
    N = math.radians((125.1228 - 0.0529538083 * n) % 360)
    i = math.radians(5.1454)
    w = math.radians((318.0634 + 0.1643573223 * n) % 360)
    a = 60.2666
    e = 0.054900
    M = math.radians((115.3654 + 13.0649929509 * n) % 360)
    E = M + e * math.sin(M) * (1 + e * math.cos(M))
    xv = a * (math.cos(E) - e)
    yv = a * math.sqrt(1 - e * e) * math.sin(E)
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    xh = r * (math.cos(N) * math.cos(v + w) -
              math.sin(N) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(N) * math.cos(v + w) +
              math.cos(N) * math.sin(v + w) * math.cos(i))
    zh = r * (math.sin(v + w) * math.sin(i))
    lon_ecl = math.atan2(yh, xh)
    lat_ecl = math.atan2(zh, math.sqrt(xh * xh + yh * yh))
    obliquity = math.radians(23.4393 - 3.563e-7 * n)
    xe = math.cos(lat_ecl) * math.cos(lon_ecl)
    ye = (math.cos(lat_ecl) * math.sin(lon_ecl) * math.cos(obliquity) -
          math.sin(lat_ecl) * math.sin(obliquity))
    ze = (math.cos(lat_ecl) * math.sin(lon_ecl) * math.sin(obliquity) +
          math.sin(lat_ecl) * math.cos(obliquity))
    ra = math.atan2(ye, xe)
    dec = math.atan2(ze, math.sqrt(xe * xe + ye * ye))
    hh = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    gmst = (6.697375 + 0.0657098242 * n + hh) % 24
    lmst = (gmst * 15 + lon) % 360
    ha = math.radians(lmst) - ra
    phi = math.radians(lat)
    alt = math.asin(math.sin(phi) * math.sin(dec) +
                    math.cos(phi) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.cos(dec) * math.sin(ha),
                    math.sin(dec) * math.cos(phi) -
                    math.cos(dec) * math.sin(phi) * math.cos(ha))
    return math.degrees(az) % 360, math.degrees(alt)


def moon_phase(dt) -> float:
    """0=新月, 0.5=满月, 1=又回新月"""
    ref = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    dt_utc = dt.astimezone(datetime.timezone.utc)
    days = (dt_utc - ref).total_seconds() / 86400.0
    return (days / 29.530588) % 1.0


def moon_brightness_factor(phase: float) -> float:
    return (1.0 - math.cos(2 * math.pi * phase)) / 2.0


# ═══════════════════════════════════════════════════════════════════
# 大气物理
# ═══════════════════════════════════════════════════════════════════
def air_mass_kasten_young(alt_deg: float) -> float:
    """Kasten-Young 大气质量公式。"""
    if alt_deg <= 0:
        return 40.0
    if alt_deg > 90:
        alt_deg = 90.0
    s = math.sin(math.radians(alt_deg))
    am = 1.0 / (s + 0.50572 * (alt_deg + 6.07995) ** -1.6364)
    return min(am, 40.0)


def _mie_tau(vis_m: float) -> float:
    """Mie 光学厚度（**仅气溶胶**，与波长近似无关）。

    【旧实现的问题】把 cloud 当成 Mie 气溶胶塞进 tau：
        tau += (cloud/100)**1.5 * 1.8
    云不是气溶胶。云量 80% 时 tau≈1.44 → 直射被 exp(-1.44·am) 灭掉，
    而漫射只降 30%：结果是"多云/阴/雨都只是整体变暗"，而不是"光变软、
    太阳时隐时现"。云的直射削减改由 cloud_direct_transmittance() 负责。
    """
    tau = 0.05
    vis = max(200.0, float(vis_m))
    # Koschmieder：能见度越低，气溶胶光学厚度越大
    vis_ratio = max(0.02, min(1.0, vis / 20000.0))
    tau += -math.log(vis_ratio) * 0.15
    return tau


def cloud_direct_transmittance(cloud: float) -> float:
    """云层对**直射太阳光**的透过率（两流近似）。

    T_dir = exp(-k · c^p)，k=2.0，p=1.4：
        c=0.00 → 1.00   晴
        c=0.50 → 0.47   多云：直射还留近一半，光斑变软变淡
        c=0.85 → 0.20   阴：几乎只剩漫射
        c=1.00 → 0.14   厚阴
    """
    c = max(0.0, min(1.0, float(cloud) / 100.0))
    K, P = 2.0, 1.4
    return float(math.exp(-K * (c ** P)))


# 云量 → 天光漫射倍率（薄云把直射转成漫射，会**增强**环境光；
# 厚阴云整体削弱）。写成表而不是公式，是为了可读、可测、可调。
_CLOUD_DIFFUSE_TABLE = ((0.00, 1.00), (0.30, 1.18), (0.60, 1.35),
                        (0.80, 1.15), (1.00, 0.72))


def sky_diffuse_factor(cloud: float) -> float:
    """云量对天光漫射的倍率（分段线性插值，见 _CLOUD_DIFFUSE_TABLE）。"""
    c = max(0.0, min(1.0, float(cloud) / 100.0))
    tab = _CLOUD_DIFFUSE_TABLE
    for i in range(len(tab) - 1):
        c0, f0 = tab[i]
        c1, f1 = tab[i + 1]
        if c <= c1:
            t = 0.0 if c1 <= c0 else (c - c0) / (c1 - c0)
            return float(f0 + (f1 - f0) * t)
    return float(tab[-1][1])


# ═══════════════════════════════════════════════════════════════════
# WMO 天气码 → 天气类型（API 的 code 之前完全没用上）
# ═══════════════════════════════════════════════════════════════════
WMO_CATEGORY = {
    0: "clear", 1: "clear", 2: "cloudy", 3: "overcast",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "shower", 81: "shower", 82: "shower",
    85: "snow", 86: "snow",
    95: "thunder", 96: "thunder", 99: "thunder",
}


def categorize_code(code) -> str:
    """WMO code → 内部天气类型（未知返回 ""）。"""
    try:
        return WMO_CATEGORY.get(int(code), "")
    except (TypeError, ValueError):
        return ""


# ═══════════════════════════════════════════════════════════════════
# 阵雨 / 雷阵雨的「间歇性」
# ═══════════════════════════════════════════════════════════════════
def _hash01(salt: int, k: int) -> float:
    """确定性哈希 → [0,1)。同一输入永远同一输出（可复现）。"""
    h = (int(k) * 2654435761 + int(salt) * 40503) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return ((h >> 8) & 0xFFFFFF) / float(0x1000000)


def _vnoise(salt: int, minutes: float, period_min: float) -> float:
    """时间轴上的值噪声（平滑插值），用于"云开云合"。"""
    x = minutes / max(1.0, float(period_min))
    i0 = math.floor(x)
    f = x - i0
    a = _hash01(salt, i0)
    b = _hash01(salt, i0 + 1)
    s = f * f * (3.0 - 2.0 * f)          # smoothstep
    return a + (b - a) * s


def shower_dynamics(dt, cloud: float, precip: float, kind: str = "shower"):
    """阵雨/雷阵雨的间歇性：返回 (cloud_eff, precip_eff, burst)。

    阵雨不是"一直下的小雨"，而是**云在开合**：一阵雨、一阵停，
    太阳在云缝里漏下来。这里用 dt 的确定性噪声建模，所以：
      · 同一时刻重跑结果一致（可复现、可续跑）
      · 一整天的帧序列里，雨会有起有落（延时视频才好看）

    burst ∈ [0,1]：1 = 雨最急、云最厚；0 = 云开、太阳露脸。
    cloud_eff 在 burst=0 时**低于**基准云量（这才是"露太阳"）：
        cloud_eff = c·(0.40 + 0.60·burst) + (100-c)·0.55·burst
        c=70（阵雨基准）→ burst=0: 28%（放晴）→ burst=1: 86%（乌云）
    """
    if dt is None:
        return float(cloud), float(precip), 0.0
    minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0
    salt = 91 if kind == "shower" else 137
    period = 26.0 if kind == "shower" else 17.0
    burst = _vnoise(salt, minutes, period)
    if kind == "thunder":
        burst = min(1.0, burst ** 0.7 * 1.15)      # 雷阵雨更尖
    c = max(0.0, min(100.0, float(cloud)))
    p = max(0.0, float(precip))
    cloud_eff = min(100.0, c * (0.40 + 0.60 * burst) + (100.0 - c) * 0.55 * burst)
    precip_eff = p * (0.15 + 2.60 * burst)
    return float(cloud_eff), float(precip_eff), float(burst)


def vis_transmittance(vis_m: float, alt_deg: float) -> float:
    """能见度（气溶胶/雾霾）对**太阳辐射**的透过率。

    Koschmieder 关系给出消光系数，配合 Kasten-Young 大气质量：
        τ_a = −ln(V/20000)·0.15 ,  T = e^(−τ_a·am)

    这一步让"能见度"这个 API 字段真正参与计算（旧实现只把它当作
    补丁项塞进 Mie tau，和云混在一起，语义不清）。
    """
    vis = max(200.0, float(vis_m))
    if vis >= 20000.0:
        return 1.0
    tau_a = -math.log(max(0.02, min(1.0, vis / 20000.0))) * 0.15
    return float(math.exp(-tau_a * air_mass_kasten_young(max(0.1, alt_deg))))


def solar_irradiance(alt_deg, cloud=0.0, vis_m=20000.0) -> float:
    """归一化太阳辐照度（天顶=1.0）。用 G 通道代表整体。"""
    rgb = solar_irradiance_rgb(alt_deg, cloud, vis_m)
    return float(rgb[1])


def solar_irradiance_rgb(alt_deg, cloud=0.0, vis_m=20000.0) -> np.ndarray:
    """
    分波长太阳辐照度。返回 RGB (3,) float32 线性值。

    Rayleigh 散射：τ_r(λ) = τ_r(550) × (λ/550)^-4.08
    Mie 散射：τ_m 近似与波长无关
    大气透过率：T(λ) = exp(-(τ_r(λ) + τ_m) × am)
    """
    if alt_deg < -18:
        return np.zeros(3, dtype=np.float32)

    # 暮光分段
    if alt_deg < 0:
        if alt_deg > -6:
            base = 0.018 * (1 + alt_deg / 6)
        elif alt_deg > -12:
            base = 0.004 * (1 + (alt_deg + 6) / 6)
        else:
            base = 0.0008 * (1 + (alt_deg + 12) / 6)
        return np.array([base, base * 0.45, base * 0.20],
                        dtype=np.float32)

    am = air_mass_kasten_young(alt_deg)

    tau_r_550 = 0.098

    def _rayleigh(wl_nm):
        ratio = wl_nm / 550.0
        return tau_r_550 * (ratio ** -4.08)

    tau_r_r = _rayleigh(650.0)
    tau_r_g = _rayleigh(550.0)
    tau_r_b = _rayleigh(450.0)

    tau_m = _mie_tau(vis_m)
    # 云层整层遮挡：削直射（不分波长）。与气溶胶的 tau 分开处理。
    T_cloud = cloud_direct_transmittance(cloud)

    T_r = math.exp(-(tau_r_r + tau_m) * am) * T_cloud
    T_g = math.exp(-(tau_r_g + tau_m) * am) * T_cloud
    T_b = math.exp(-(tau_r_b + tau_m) * am) * T_cloud

    if alt_deg < 8.0:
        extra = (8.0 - alt_deg) / 8.0 * 0.5
        T_b *= math.exp(-extra * am * 0.7)
        T_g *= math.exp(-extra * am * 0.4)

    return np.clip(np.array([T_r, T_g, T_b], dtype=np.float32), 0.0, 1.0)


SKY_MAX = 0.22


def sky_irradiance(sun_alt: float, cloud=0.0) -> float:
    """
    天光（天空漫射）辐照度，相对天顶直射 = 1.0。

    物理依据：室内墙面即使没有直射光斑，仍被天空漫射照亮；
    其强度随太阳高度上升而增强（∝ sin(alt)^0.6，低角时上升快），
    并随云量衰减（云层吸收/遮挡，但散射仍保留一部分）。

        sun_alt <= 0  → 0（暮光由 twilight 分支单独处理）
        晴天正午      → ≈ 0.22
        晴天 alt=10°  → ≈ 0.13
        全阴天        → ≈ 0.10（保留 30% 散射）
    """
    if sun_alt <= 0.0:
        return 0.0
    c = max(0.0, min(100.0, float(cloud)))
    base = SKY_MAX * (math.sin(math.radians(sun_alt)) ** 0.60)
    # 云把直射转成漫射：薄云时天光反而更亮，厚阴云才整体削弱
    return base * sky_diffuse_factor(c)


def night_sky_irradiance(moon_alt: float, phase: float, cloud=0.0) -> float:
    """夜空照明：城市辉光 / 星光背景 + 月光散射。返回环境光强度。

    【旧实现的问题】夜间环境光是常数 0.02，与月亮高度、月相、云量全无关
    → 00:00 和 04:00 渲染出的图**逐像素相同**，整段夜景是静止画面。
    """
    c = max(0.0, min(1.0, float(cloud) / 100.0))
    # 1) 夜空辉光（城市光害 + 星光）：厚云会挡住大部分
    skyglow = 0.008 * (1.0 - 0.55 * c)
    # 2) 月光经大气/云层散射后的漫射照明
    moon_amb = 0.0
    if moon_alt > 0.0:
        m = moon_brightness_factor(phase)
        alt_n = max(0.0, min(1.0, float(moon_alt) / 60.0)) ** 0.7
        moon_amb = 0.035 * m * alt_n * (1.0 - 0.60 * c)
    return float(skyglow + moon_amb)


def sky_color(sun_alt: float) -> np.ndarray:
    """天光颜色（线性 RGB）。低角偏暖（地平线散射），高角偏冷（瑞利）。"""
    zenith = np.array([0.42, 0.50, 0.70], dtype=np.float32)
    horizon = np.array([0.60, 0.52, 0.52], dtype=np.float32)
    t = max(0.0, min(1.0, (sun_alt - 3.0) / 27.0))
    return horizon * (1.0 - t) + zenith * t


def moon_irradiance(moon_alt: float, phase: float, cloud=0.0) -> float:
    """归一化月光辐照度（视觉校正）。"""
    if moon_alt < 5:
        return 0.0
    alt_n = max(0.0, min(1.0, moon_alt / 60.0)) ** 0.7
    am = air_mass_kasten_young(max(0.1, moon_alt))
    tau = 0.20 + (cloud / 100.0) ** 1.5 * 1.8
    trans = math.exp(-tau * am)
    phase_factor = moon_brightness_factor(phase)
    FULL_MOON_TOP = 0.20
    return FULL_MOON_TOP * alt_n * trans * phase_factor


def moon_color_rgb(moon_alt: float) -> np.ndarray:
    """
    月光分波长颜色（线性 RGB）。

    sRGB 视觉色 (0.62, 0.72, 0.95) → 线性 (0.34, 0.48, 0.90)
    低角时轻微偏暖（大气衰减），暖色 (0.63, 0.38, 0.14) 已线性
    """
    base = np.array([0.34, 0.48, 0.90], dtype=np.float32)
    if moon_alt < 20:
        warm = (20 - moon_alt) / 20.0 * 0.3
        warm_color = np.array([0.63, 0.38, 0.14], dtype=np.float32)
        base = base * (1.0 - warm) + warm_color * warm
    return base


# ═══════════════════════════════════════════════════════════════════
# 颜色
# ═══════════════════════════════════════════════════════════════════
def blackbody_to_rgb(T: float) -> np.ndarray:
    """黑体辐射温度 → sRGB (0-1)。"""
    T = max(1000.0, min(40000.0, T))
    T100 = T / 100.0
    if T100 <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(T100) - 161.1195681661
        if T100 <= 19:
            b = 0.0
        else:
            b = 138.5177312231 * math.log(T100 - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((T100 - 60) ** -0.1332047592)
        g = 288.1221695283 * ((T100 - 60) ** -0.0755148492)
        b = 255.0
    return np.clip(np.array([r, g, b], dtype=np.float32), 0, 255) / 255.0


def sun_color_from_altitude(alt_deg: float) -> np.ndarray:
    """太阳高度角 → sRGB 色温（保留兼容）。"""
    if alt_deg >= 60:
        T = 6500.0
    elif alt_deg >= 20:
        T = 4500 + (alt_deg - 20) / 40.0 * 2000
    elif alt_deg >= 5:
        T = 2800 + (alt_deg - 5) / 15.0 * 1700
    elif alt_deg >= 0:
        T = 1800 + alt_deg / 5.0 * 1000
    else:
        T = 1500.0
    return blackbody_to_rgb(T)


def twilight_color(alt_deg: float) -> np.ndarray:
    """暮光颜色渐变（保留兼容）。"""
    if alt_deg >= 0:
        return sun_color_from_altitude(alt_deg)
    stops = [(0, [1.00, 0.46, 0.20]), (-2, [0.85, 0.32, 0.20]),
             (-4, [0.62, 0.26, 0.32]), (-6, [0.42, 0.22, 0.45]),
             (-9, [0.28, 0.20, 0.55]), (-12, [0.18, 0.18, 0.58]),
             (-15, [0.10, 0.14, 0.48]), (-18, [0.05, 0.08, 0.32])]
    if alt_deg <= -18:
        return np.array(stops[-1][1], dtype=np.float32)
    for i in range(len(stops) - 1):
        v0, c0 = stops[i]
        v1, c1 = stops[i + 1]
        if v1 <= alt_deg <= v0:
            t = (alt_deg - v0) / (v1 - v0)
            return np.array([c0[j] + (c1[j] - c0[j]) * t for j in range(3)],
                            dtype=np.float32)
    return np.array(stops[-1][1], dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════
# 天气数据结构
# ═══════════════════════════════════════════════════════════════════
WMO_CODES = {
    0: "晴", 1: "基本晴", 2: "少云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨", 61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "中阵雨", 82: "强阵雨",
    95: "雷暴", 96: "雷暴+冰雹", 99: "强雷暴",
}


class WeatherInfo:
    def __init__(self, cloud=0, vis=20000, humidity=50,
                 precip=0.0, code=0, temp=20.0, forced_type=None):
        self.cloud = cloud
        self.vis = vis
        self.humidity = humidity
        self.precip = precip
        self.code = code
        self.temp = temp
        self.forced_type = forced_type

    @property
    def description(self) -> str:
        if self.forced_type and self.forced_type != "auto":
            return f"[{config.WEATHER_LABELS.get(self.forced_type, self.forced_type)}]"
        return WMO_CODES.get(self.code, f"未知({self.code})")

    @property
    def weather_type(self) -> str:
        if self.forced_type and self.forced_type != "auto":
            return self.forced_type
        if self.precip > 0.5 and self.temp < 2:
            return "snow"
        if self.precip > 0.1:
            return "rain"
        if self.vis < 5000:
            return "haze"
        if self.cloud < 25:
            return "clear"
        if self.cloud < 65:
            return "cloudy"
        return "overcast"

    @property
    def color_shift(self) -> np.ndarray:
        shift = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        if self.humidity > 50:
            shift[2] *= (1.0 + (self.humidity - 50) * 0.0018)
        if self.vis < 20000:
            shift[0] *= (1.0 + (20000 - self.vis) * 0.00003)
        if self.cloud > 30:
            cool = (self.cloud - 30) / 70.0
            shift[0] *= (1.0 - 0.08 * cool)
            shift[2] *= (1.0 + 0.05 * cool)
        if self.weather_type == "rain":
            shift[2] *= 1.10
            shift[0] *= 0.95
        elif self.weather_type == "snow":
            shift[2] *= 1.15
            shift[0] *= 0.92
        return shift


# ═══════════════════════════════════════════════════════════════════
# 天气获取
# ═══════════════════════════════════════════════════════════════════
def fetch_weather(lat, lon, timeout=8) -> Optional[WeatherInfo]:
    """从 Open-Meteo 获取当前天气。失败返回 None。"""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ("cloudcover,visibility,relative_humidity_2m,"
                    "precipitation,weathercode,temperature_2m"),
        "timezone": "auto",
    }
    try:
        import requests          # 延迟导入：环境缺 requests 时自动降级（返回 None）
        r = requests.get(config.OPEN_METEO_URL, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json().get("current", {})
        return WeatherInfo(
            cloud=data.get("cloudcover", 0),
            vis=data.get("visibility", 20000),
            humidity=data.get("relative_humidity_2m", 50),
            precip=data.get("precipitation", 0.0),
            code=data.get("weathercode", 0),
            temp=data.get("temperature_2m", 20.0),
        )
    except Exception as e:
        config.LOG.warn(f"天气查询失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# NTP 查询
# ═══════════════════════════════════════════════════════════════════
def query_ntp(host, timeout=3.0) -> Optional[datetime.datetime]:
    """查询 NTP 服务器。失败返回 None。返回 UTC datetime（带 tz）。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"\x1b" + 47 * b"\0", (host, 123))
        data, _ = sock.recvfrom(1024)
        sock.close()
        if len(data) < 48:
            return None
        sec = struct.unpack("!12I", data[:48])[10]
        return datetime.datetime.fromtimestamp(
            sec - config.NTP_EPOCH_DELTA, tz=datetime.timezone.utc)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# 地理定位查询
# ═══════════════════════════════════════════════════════════════════
# ── 运行环境探测 ──────────────────────────────────────────────
EXTRA_BIN_DIRS = [
    "/system/bin", "/system/xbin", "/vendor/bin", "/data/local/bin",
    (os.environ.get("PREFIX", "") + "/bin") if os.environ.get("PREFIX") else "",
    "/data/data/com.termux/files/usr/bin",
    "/opt/homebrew/bin", "/usr/local/bin", "/snap/bin",
]


def find_cmd(name):
    """在 PATH 及常见额外目录里查找可执行文件。"""
    p = shutil.which(name)
    if p:
        return p
    for d in EXTRA_BIN_DIRS:
        if not d:
            continue
        q = os.path.join(d, name)
        try:
            if os.path.isfile(q) and os.access(q, os.X_OK):
                return q
        except OSError:
            continue
    return None


def detect_env():
    """运行环境：termux / android / linux / macos / windows / unknown。"""
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get(
            "PREFIX", ""):
        return "termux"
    if os.name == "nt" or sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if os.path.exists("/system/bin/dumpsys") or find_cmd("dumpsys"):
        return "android"
    try:
        if "android" in os.uname().release.lower():
            return "android"
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _run(cmd, timeout=8):
    """执行命令，返回 stdout（失败返回空串）。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


_COORD_RE = re.compile(r"(-?\d{1,3}\.\d{2,})\s*[, ]\s*(-?\d{1,3}\.\d{2,})")


def _pick_coords(text, lat_first=True):
    """从任意文本里抠出一组合法经纬度。"""
    m = _COORD_RE.search(text or "")
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    lat, lon = (a, b) if lat_first else (b, a)
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


# ── 各环境定位 provider（统一返回 (lat, lon, city, src) 或 None）──
def _p_termux():
    """Termux + termux-api。"""
    exe = find_cmd("termux-location")
    if not exe:
        return None
    for provider in ("gps", "network", "passive"):
        out = _run([exe, "-p", provider, "-r", "once"], timeout=15)
        try:
            d = json.loads(out)
        except Exception:
            continue
        if d.get("latitude") is not None:
            return (float(d["latitude"]), float(d["longitude"]),
                    "GPS", f"termux/{provider}")
    return None


def _p_android():
    """Android：dumpsys / cmd location（可选经 su 提权）。"""
    bases = [["dumpsys", "location"],
             ["cmd", "location", "last-known-location"],
             ["cmd", "location", "providers"]]
    for base in bases:
        exe = find_cmd(base[0])
        if not exe:
            continue
        got = _pick_coords(_run([exe] + base[1:], timeout=8))
        if got:
            return (got[0], got[1], "GPS", "android/" + base[0])
    try:
        use_su = bool(config.get_defaults().get("location_use_su", False))
    except Exception:
        use_su = False
    if use_su:
        su = find_cmd("su")
        if su:
            for base in bases:
                got = _pick_coords(_run([su, "-c", " ".join(base)], timeout=12))
                if got:
                    return (got[0], got[1], "GPS", "android-su/" + base[0])
    return None


def _p_geoclue():
    """Linux 桌面：GeoClue 演示程序。"""
    for name in ("where-am-i", "geoclue-where-am-i"):
        exe = find_cmd(name)
        if not exe:
            continue
        out = _run([exe], timeout=12)
        la = re.search(r"[Ll]atitude[:：]\s*(-?\d+\.\d+)", out)
        lo = re.search(r"[Ll]ongitude[:：]\s*(-?\d+\.\d+)", out)
        if la and lo:
            return (float(la.group(1)), float(lo.group(1)), "GeoClue", "geoclue")
    return None


def _p_gpsd():
    """Linux：gpsd 守护进程。"""
    exe = find_cmd("gpspipe")
    if not exe:
        return None
    out = _run([exe, "-w", "-n", "12"], timeout=12)
    la = re.search(r'"lat"\s*:\s*(-?\d+\.\d+)', out)
    lo = re.search(r'"lon"\s*:\s*(-?\d+\.\d+)', out)
    if la and lo:
        return (float(la.group(1)), float(lo.group(1)), "GPSD", "gpsd")
    return None


def _p_modem():
    """Linux：ModemManager（蜂窝/GNSS 模块）。"""
    exe = find_cmd("mmcli")
    if not exe:
        return None
    out = _run([exe, "-m", "any", "--location-get"], timeout=12)
    la = re.search(r"latitude[:：]\s*(-?\d+\.\d+)", out, re.I)
    lo = re.search(r"longitude[:：]\s*(-?\d+\.\d+)", out, re.I)
    if la and lo:
        return (float(la.group(1)), float(lo.group(1)), "Modem", "mmcli")
    return None


def _p_macos():
    """macOS：CoreLocationCLI / whereami / locationcli。"""
    for name in ("CoreLocationCLI", "whereami", "locationcli"):
        exe = find_cmd(name)
        if not exe:
            continue
        out = _run([exe, "-once"] if name == "CoreLocationCLI" else [exe],
                   timeout=15)
        got = _pick_coords(out)
        if got:
            return (got[0], got[1], "CoreLocation", name)
    return None


def _p_windows():
    """Windows：Geolocator（PowerShell + WinRT）。"""
    ps = find_cmd("powershell") or find_cmd("pwsh")
    if not ps:
        return None
    script = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
        "$g=New-Object Windows.Devices.Geolocation.Geolocator;"
        "$p=$g.GetGeopositionAsync().GetAwaiter().GetResult();"
        "'{0} {1}' -f $p.Coordinate.Point.Position.Latitude,"
        "$p.Coordinate.Point.Position.Longitude")
    got = _pick_coords(_run([ps, "-NoProfile", "-Command", script], timeout=20))
    if got:
        return (got[0], got[1], "Windows", "winrt")
    return None


# 时区 → 代表坐标（离线兜底，仅供太阳位置估算）
TZ_TABLE = {
    "Asia/Shanghai": (31.23, 121.47, "上海"),
    "Asia/Chongqing": (29.56, 106.55, "重庆"),
    "Asia/Urumqi": (43.83, 87.62, "乌鲁木齐"),
    "Asia/Hong_Kong": (22.32, 114.17, "香港"),
    "Asia/Taipei": (25.03, 121.57, "台北"),
    "Asia/Tokyo": (35.68, 139.65, "东京"),
    "Asia/Seoul": (37.57, 126.98, "首尔"),
    "Asia/Singapore": (1.35, 103.82, "新加坡"),
    "Asia/Bangkok": (13.76, 100.50, "曼谷"),
    "Asia/Kolkata": (22.57, 88.36, "加尔各答"),
    "Asia/Dubai": (25.20, 55.27, "迪拜"),
    "Europe/London": (51.51, -0.13, "伦敦"),
    "Europe/Paris": (48.86, 2.35, "巴黎"),
    "Europe/Berlin": (52.52, 13.40, "柏林"),
    "Europe/Moscow": (55.76, 37.62, "莫斯科"),
    "America/New_York": (40.71, -74.01, "纽约"),
    "America/Chicago": (41.88, -87.63, "芝加哥"),
    "America/Denver": (39.74, -104.99, "丹佛"),
    "America/Los_Angeles": (34.05, -118.24, "洛杉矶"),
    "America/Sao_Paulo": (-23.55, -46.63, "圣保罗"),
    "Australia/Sydney": (-33.87, 151.21, "悉尼"),
    "Pacific/Auckland": (-36.85, 174.76, "奥克兰"),
    "Africa/Cairo": (30.04, 31.24, "开罗"),
    "Africa/Johannesburg": (-26.20, 28.05, "约翰内斯堡"),
}


def utc_offset_hours():
    """当前进程的 UTC 偏移（小时），取不到返回 None。"""
    try:
        off = datetime.datetime.now().astimezone().utcoffset()
        if off is None:
            return None
        return off.total_seconds() / 3600.0
    except Exception:
        return None


def system_timezone():
    """尽力取得 IANA 时区名。"""
    # POSIX: TZ 环境变量优先
    tz = os.environ.get("TZ", "").strip()
    if tz and "/" in tz:
        return _norm_tz(tz)
    for cmd in (["timedatectl", "show", "-p", "Timezone", "--value"],
                ["cat", "/etc/timezone"]):
        exe = find_cmd(cmd[0])
        if not exe:
            continue
        out = _run([exe] + cmd[1:], timeout=5).strip()
        if out and "/" in out:
            return _norm_tz(out.splitlines()[0].strip())
    try:
        p = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in p:
            return _norm_tz(p.split("zoneinfo/")[-1])
    except Exception:
        pass
    return ""


def _norm_tz(tz):
    """/etc/timezone 常见的 Etc/UTC、GMT 等归一化。"""
    tz = (tz or "").strip()
    if tz.startswith("Etc/"):
        tz = tz[4:]
    if tz in ("GMT", "GMT0", "UCT", "Universal", "Zulu"):
        tz = "UTC"
    return tz


def _p_timezone():
    """离线兜底：时区代表坐标；无表项时按 UTC 偏移估算经度。"""
    tz = system_timezone()
    if tz in TZ_TABLE:
        lat, lon, city = TZ_TABLE[tz]
        return (lat, lon, city, f"tz/{tz}")
    off = utc_offset_hours()
    if off:
        # 偏移 → 经度：本地时 = UTC + off，对应经度 ≈ off × 15°（东正西负）
        return (0.0, max(-180.0, min(180.0, off * 15.0)),
                f"UTC{off:+g} 估算", f"tz/offset{off:+g}")
    return None


LOCATION_PROVIDERS = [
    ("termux", "Termux（termux-api）", _p_termux),
    ("android", "Android（dumpsys / cmd location）", _p_android),
    ("geoclue", "Linux GeoClue", _p_geoclue),
    ("gpsd", "Linux gpsd", _p_gpsd),
    ("modem", "Linux ModemManager", _p_modem),
    ("macos", "macOS CoreLocation", _p_macos),
    ("windows", "Windows Geolocator", _p_windows),
    ("timezone", "时区推算（离线兜底）", _p_timezone),
]


def available_providers():
    """返回 ([{key,label,available,env,current}], 当前环境)。"""
    env = detect_env()
    dep = {
        "termux": bool(find_cmd("termux-location")),
        "android": bool(find_cmd("dumpsys") or find_cmd("cmd")),
        "geoclue": bool(find_cmd("where-am-i")
                        or find_cmd("geoclue-where-am-i")),
        "gpsd": bool(find_cmd("gpspipe")),
        "modem": bool(find_cmd("mmcli")),
        "macos": bool(find_cmd("CoreLocationCLI") or find_cmd("whereami")),
        "windows": bool(find_cmd("powershell") or find_cmd("pwsh")),
        "timezone": bool(system_timezone()),
    }
    out = []
    for key, label, _ in LOCATION_PROVIDERS:
        out.append({"key": key, "label": label,
                    "available": dep.get(key, False),
                    "env": env, "current": key == env})
    return out, env


def _enabled_providers():
    """按设置筛选 provider（空 = 全部，按优先级）。"""
    try:
        want = config.get_defaults().get("location_providers") or []
    except Exception:
        want = []
    if want:
        keys = set(want)
        return [(k, l, f) for k, l, f in LOCATION_PROVIDERS if k in keys]
    return list(LOCATION_PROVIDERS)


def try_system_gps(providers=None):
    """跨环境「本机定位」。返回 (lat, lon, city, src) 或 None。

    顺序：Termux → Android → GeoClue → gpsd → ModemManager →
          macOS → Windows → 时区兜底 → 本地缓存
    """
    for _key, _label, fn in (providers or _enabled_providers()):
        try:
            got = fn()
        except Exception:
            got = None
        if got:
            return got
    return load_device_location()


def load_device_location(max_age_days=3650):
    """读取本机定位缓存。返回 (lat, lon, city, src) 或 None。"""
    try:
        with open(config.CONFIG_LOCATION, "r", encoding="utf-8") as f:
            d = json.load(f)
        lat, lon = float(d["lat"]), float(d["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        age = time.time() - float(d.get("ts", 0) or 0)
        if max_age_days and age > max_age_days * 86400:
            return None
        return (lat, lon, d.get("city") or "本机定位",
                d.get("src") or "cache")
    except Exception:
        return None


def save_device_location(lat, lon, city="", src="manual"):
    """写入本机定位缓存。"""
    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.CONFIG_LOCATION, "w", encoding="utf-8") as f:
            json.dump({"lat": round(float(lat), 6),
                       "lon": round(float(lon), 6),
                       "city": city or "",
                       "src": src or "manual",
                       "ts": time.time()}, f,
                      ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def try_ip_services(services=None):
    """遍历 IP 地理服务，返回全部成功结果（按顺序）。"""
    out = []
    for svc in (services or config.GEO_SERVICES):
        res = try_ip_service(svc)
        if res:
            lat, lon, city, region, country, name = res
            out.append({"lat": lat, "lon": lon, "city": city,
                        "region": region, "country": country, "name": name})
    return out


def try_ip_service(svc):
    """查询单个 IP 地理服务。返回 (lat, lon, city, region, country, name) 或 None。"""
    name, _, url, parser = svc
    try:
        import requests          # 延迟导入：缺 requests 直接当作"服务不可用"
        r = requests.get(url, timeout=8,
                         headers={"User-Agent": f"{config.PROG}/{config.VERSION}"})
        r.raise_for_status()
        lat, lon, city, region, country = parser(r.json())
        if lat is not None:
            return (float(lat), float(lon), city or "?", region or "?",
                    country or "?", name)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════
def _self_test():
    """验证分波长大气散射 + 月光颜色。"""
    print("分波长太阳辐照度（云=0，能见度=20km）：")
    print(f"{'alt':>6}  {'R':>7}  {'G':>7}  {'B':>7}   色彩倾向")
    for alt in [90, 60, 30, 20, 10, 5, 2, 1, 0, -2, -4, -6, -10, -15, -18]:
        rgb = solar_irradiance_rgb(alt, cloud=0, vis_m=20000)
        if rgb[1] > 1e-6:
            ratio_rb = rgb[0] / max(rgb[2], 1e-6)
        else:
            ratio_rb = 0
        if ratio_rb > 1.5:
            trend = "偏橙红"
        elif ratio_rb > 1.15:
            trend = "偏暖"
        elif ratio_rb > 0.9:
            trend = "接近白色"
        else:
            trend = "偏冷"
        print(f"{alt:>6}  {rgb[0]:>7.4f}  {rgb[1]:>7.4f}  "
              f"{rgb[2]:>7.4f}   {trend}")

    print("\n月光颜色（线性）：")
    for alt in [5, 10, 20, 45, 80]:
        rgb = moon_color_rgb(alt)
        print(f"  alt={alt:>3}° → RGB={rgb.tolist()}")


if __name__ == "__main__":
    _self_test()