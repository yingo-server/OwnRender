#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大气 / 天气物理 —— 把 API 的每个字段都接进渲染计算。

设计原则（很重要）
══════════════════════════════════════════════════════════════════════
1. **参数必须真实**：凡是能用物理关系或公开经验式算出来的，就不要手调表。
   （前一版的 WEATHER_LOOK 是反面教材：9 种天气 × 7 个手调数字，
     等于把"物理"退化成"美工调色"，而且天气之间彼此不自洽。）
2. **显示异常 = 参数没对接**：问题的本质是 API 给的信息没进计算。
   本模块负责把 cloud / precip / temp / vis / humidity / WMO code
   这些"网络信息"全部接进光照链路。
3. **全局手调参数 ≤ 5 个**，见下（其余全部由物理量与几何推导）：

   ┌── 全局可调参数（全部有出处）────────────────────────────┐
   │ EYE_ADAPT_GAMMA      视觉适应幂律指数（Stevens 幂律 0.33~0.5）│
   │ TAU_CLOUD_THICK      厚云光学厚度（直射透过率 e^-τ）          │
   │ WATER_FILM_REF_MM    水膜饱和降水率（mm/h）                   │
   │ GROUND_ALBEDO        地面反照率（雪/湿/干 —— 材料常数）        │
   │ TONE_S_CURVE_GAIN    光硬度→对比度的映射增益                  │
   └──────────────────────────────────────────────────────┘

用到的公开模型
──────────────────────────────────────────────────────────────────────
· Kasten-Young (1989)          大气质量
· Koschmieder (1924)           能见度 → 散射系数 β = 3.912 / V
· Badescu / Kasten 型云修正因子  CMF ≈ 1 − 0.75·c^3.4（云量→总辐照）
· 覆盖加权直射透过率（断裂云）  T = (1−c) + c·e^(−τ)
· 能量守恒                     漫射 = 总辐照预算 − 直射贡献
· 地面反照率按材料取值         雪 0.80 / 湿 0.07 / 干 0.25
"""
import math

import numpy as np

from . import astro


# ═══════════════════════════════════════════════════════════════════
# ① 全局参数（就这 5 个）
# ═══════════════════════════════════════════════════════════════════
EYE_ADAPT_GAMMA = 0.40      # 视觉适应指数（Stevens 幂律；文献 0.33~0.5）
TAU_CLOUD_THICK = 3.0       # 厚云光学厚度 → 直射透过率 e^-3 ≈ 5%
WATER_FILM_REF_MM = 0.50    # 降水率到这个值，表面水膜接近全覆盖
GROUND_ALBEDO = {           # 地面反照率（材料常数，不是风格参数）
    "snow": 0.80,
    "wet":  0.07,
    "dry":  0.25,
}
TONE_S_CURVE_GAIN = 0.30    # 光硬度 → 对比度：contrast = 1 − gain·(1−hard)

# 文本常量（教科书常数，非可调参数）
KOSCHMIEDER_K = 3.912       # 能见度 → 散射系数
TWILIGHT_ALT_DEG = 10.0     # 低于此太阳高度按暮光处理（视觉暗适应）


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ═══════════════════════════════════════════════════════════════════
# ② 云 → 直射 / 漫射（能量守恒，不用调参）
# ═══════════════════════════════════════════════════════════════════
def direct_transmittance(cloud: float) -> float:
    """云对直射的透过率（覆盖加权）。

    云量是**覆盖率**，不是光学厚度：云量 50% 意味着"太阳有一半时间
    被挡住" → 直射 ≈ 一半 × 晴空 + 一半 × 厚云透过：

        T(c) = (1 − c) + c·e^(−τ)，  τ = TAU_CLOUD_THICK

    c=0    → 1.00   晴
    c=0.50 → 0.525  多云：太阳时不时被云挡，光斑变软变淡
    c=0.85 → 0.190  阴
    c=1.00 → 0.050  厚阴：直射基本消失
    """
    c = _clamp(float(cloud) / 100.0)
    return (1.0 - c) + c * math.exp(-TAU_CLOUD_THICK)


def cloud_modification(cloud: float) -> float:
    """云修正因子 CMF：地面总辐照相对晴空的比值。

    经验式（Badescu/Kasten 型）：CMF = 1 − 0.75·c^3.4
        c=0.50 → 0.93      c=0.85 → 0.57      c=1.00 → 0.25
    （实测世界：全阴天正午总辐照约为晴空的 20%~30%，与此一致）
    """
    c = _clamp(float(cloud) / 100.0)
    return max(0.05, 1.0 - 0.75 * (c ** 3.4))

def split_irradiance(clear_beam: float, clear_diffuse: float,
                     sun_alt: float, cloud: float,
                     vis_m: float = 20000.0):
    """把晴空的 (直射, 漫射) 换算成当前天气下的 (直射, 漫射)。

    直射：覆盖加权云透过率 × 气溶胶（能见度）透过率
    漫射：云修正因子给出**总辐照预算**，减去直射的水平分量，剩下的
          全部按能量守恒变成漫射（且不低于晴空漫射）。

    这一步替代了旧实现里 "云 = Mie 气溶胶" 的错误：
    旧代码把 cloud 塞进 tau，于是云量只让画面整体变暗，
    既不产生"漫射变多"，也不产生"云缝露太阳"。
    """
    cz = max(0.05, math.sin(math.radians(max(0.0, float(sun_alt)))))
    t_vis = astro.vis_transmittance(vis_m, sun_alt)   # 气溶胶/雾霾
    beam = float(clear_beam) * direct_transmittance(cloud) * t_vis
    ghi_clear = float(clear_diffuse) + float(clear_beam) * cz
    ghi = ghi_clear * cloud_modification(cloud) * t_vis
    diffuse = max(float(clear_diffuse) * t_vis, ghi - beam * cz)
    return beam, diffuse


# ═══════════════════════════════════════════════════════════════════
# ③ 地面 / 水膜 / 空气光
# ═══════════════════════════════════════════════════════════════════
def ground_state(temp: float, precip: float) -> str:
    """地面状态：积雪 / 湿 / 干（由降水与气温判定）。"""
    if float(precip) > 0.05:
        return "snow" if float(temp) < 2.0 else "wet"
    return "dry"


def ground_bounce(temp: float, precip: float) -> float:
    """地面反弹系数 = 地面反照率（雪地会把大量光反打回墙面）。

    旧实现完全没有这一项 → 雪天渲染得比晴天还暗 2.4 倍（物理反了）。
    """
    return float(GROUND_ALBEDO.get(ground_state(temp, precip), 0.25))


def water_film(precip: float) -> float:
    """降水 → 表面水膜覆盖率（0~1）。单调上升并饱和。"""
    p = max(0.0, float(precip))
    if p <= 0.0:
        return 0.0
    return _clamp(1.0 - math.exp(-p / WATER_FILM_REF_MM))


def airlight_fraction(vis_m: float, path_m: float) -> float:
    """空气光占比 = 1 − e^(−β·L)，β = 3.912 / 能见度。

    ⚠ 真实结论：室内光程只有几米，即使雾天(500m)也只有百分之几。
    所以"雾感"不靠这个硬凑（那是不真实的），而应来自窗外的景。
    """
    beta = KOSCHMIEDER_K / max(50.0, float(vis_m))
    return _clamp(1.0 - math.exp(-beta * max(0.0, float(path_m))))


def aperture_illuminance(P, scene, valid):
    """窗口作为**面光源**在墙面上产生的相对照度场（纯几何，无手调参数）。

    物理：有限面积光源的照度
        E ∝ A_win · cosθ_win · cosθ_wall / r²
    其中 r 是墙点到窗中心的距离，两个 cos 是窗面法线与墙面法线的夹角余弦。

    这是"靠窗亮、离窗暗"的来源。
    旧实现里环境光是全图一个常数 → 阴天（没有光斑）整张图是一块平灰，
    实测动态范围被压到 0.224~0.444。
    """
    y0, y1, z0, z1 = scene.win_bbox
    cy = 0.5 * (y0 + y1)          # 窗中心 y
    cz = 0.5 * (z0 + z1)          # 窗中心 z

    dx = float(getattr(scene, "win_x", 0.0)) - P[..., 0]   # 到窗面（±X 平面）
    dy = cy - P[..., 1]
    dz = cz - P[..., 2]
    r2 = dx * dx + dy * dy + dz * dz
    r = np.sqrt(np.maximum(r2, 1e-6))

    area = max(1e-6, (y1 - y0) * (z1 - z0))                 # 窗面积
    cos_win = np.abs(dx) / r                                # 窗面法线 · 视线
    cos_wall = np.abs(dz) / r                               # 墙面法线 · 视线
    e = area * cos_win * cos_wall / r2
    e = np.where(valid, e, 0.0)
    m = float(e[valid].mean()) if bool(valid.any()) else float(e.mean())
    return e / max(m, 1e-12)


# ═══════════════════════════════════════════════════════════════════
# ④ 视觉适应（曝光）
# ═══════════════════════════════════════════════════════════════════
def eye_exposure_ev(illuminance: float, ref: float = 1.0,
                    sun_alt: float = 45.0) -> float:
    """人眼/相机的曝光适应倍率。

    物理/心理物理依据：Stevens 幂律 —— 主观亮度 B ∝ L^γ（γ≈0.33~0.5）。
    所以当照度变成 1/k 时，观感只暗 k^γ 倍，剩下的由"适应"补掉：

        EV = (ref / E)^γ

    暮光权重：太阳低于 10° 时人眼转入暗适应（夜就是夜），
    按高度角平滑淡出适应，避免日落时分被"提亮成白天"。

    为什么必须有：晴天正午总照度 ≈1.0，阴雨天只有 ≈0.2~0.5。
    不做适应，阴雨天就是"晴天的四分之一亮" → 发闷、像坏掉。
    """
    if illuminance <= 0.0:
        return 1.0
    w = _clamp(max(0.0, float(sun_alt)) / TWILIGHT_ALT_DEG)
    if w <= 0.0:
        return 1.0
    ev_raw = (float(ref) / float(illuminance)) ** EYE_ADAPT_GAMMA
    ev = 1.0 + w * (ev_raw - 1.0)
    return float(max(0.25, min(4.0, ev)))


# ═══════════════════════════════════════════════════════════════════
# ⑤ 光质（全部由上面的物理量推导，不查表）
# ═══════════════════════════════════════════════════════════════════
def derive(cloud: float, precip: float, temp: float, vis_m: float,
           humidity: float, sun_alt: float, path_m: float,
           clear_beam: float, clear_diffuse: float) -> dict:
    """把天气/几何原始量推导成光照所需的全部"光质"量。"""
    beam, diffuse = split_irradiance(clear_beam, clear_diffuse,
                                     sun_alt, cloud, vis_m)
    total = beam + diffuse
    hard = (beam / total) if total > 1e-9 else 0.0      # 光硬度（直射占比）
    wet = water_film(precip)
    bounce = ground_bounce(temp, precip)
    air = airlight_fraction(vis_m, path_m)
    return {
        "beam": beam,
        "diffuse": diffuse,
        "hardness": float(hard),
        # 硬光 → 对比度高；软光（阴雨）→ 对比度低。线性映射，无额外参数。
        "contrast": float(1.0 - TONE_S_CURVE_GAIN * (1.0 - hard)),
        # 湿表面：漫反射被水膜压暗、镜面变强 → 观感更"艳"
        "wet": float(wet),
        "saturation": float(1.0 + 0.10 * wet - 0.20 * air),
        "bounce": float(bounce),
        "airlight": float(air),
        "ground": ground_state(temp, precip),
    }