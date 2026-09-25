#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — 光斑 mask 渲染（15 层）

职责：
  平行四边形窗格 / 最小缝隙保护 / 玻璃噪声 / 方向性透射 / 窗框暗线
  / 污渍 / 水痕 / 焦散 / 灰尘 / Bloom / 玻璃结构 / 材质裂纹
  / 墙面微凸起 / 半影 / 菲涅尔边缘 / 光渗 / 年代感

不 import 本框架其他文件。
只 import config + utils（本框架）。
被 pipeline.py 编排调用。
"""
from typing import Tuple, Dict, Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 层 1：平行四边形窗格
# ═══════════════════════════════════════════════════════════════════
def _render_parallelogram_grid(W, H, cx, cy, w, h, shear_x,
                                grid_rows, grid_cols,
                                frame_ratio, ssaa=4,
                                min_frame_px=5.0):
    """平行四边形窗格 mask（含最小缝隙像素保护）。"""
    SSAA_INNER = max(4, int(ssaa))
    if W * H * SSAA_INNER * SSAA_INNER > 40_000_000:
        SSAA_INNER = max(2, int((40_000_000 / (W * H)) ** 0.5))
    Ws, Hs = W * SSAA_INNER, H * SSAA_INNER

    half_w = w * W / 2.0
    half_h = h * H / 2.0
    cx_px = cx * W
    cy_px = cy * H
    shear_px = shear_x * W * 0.5

    corners = [
        (cx_px - half_w, cy_px - half_h),
        (cx_px + half_w, cy_px - half_h + shear_px),
        (cx_px + half_w, cy_px + half_h + shear_px),
        (cx_px - half_w, cy_px + half_h),
    ]

    canvas = Image.new("L", (Ws, Hs), 0)
    mdraw = ImageDraw.Draw(canvas)

    def _bil(u, v):
        xt = corners[0][0] + u * (corners[1][0] - corners[0][0])
        yt = corners[0][1] + u * (corners[1][1] - corners[0][1])
        xb = corners[3][0] + u * (corners[2][0] - corners[3][0])
        yb = corners[3][1] + u * (corners[2][1] - corners[3][1])
        return xt + v * (xb - xt), yt + v * (yb - yt)

    # 最小缝隙保护
    cell_h = h * H / max(grid_rows, 1)
    cell_w = w * W / max(grid_cols, 1)
    min_cell = min(cell_h, cell_w)
    eff_frame_ratio = frame_ratio
    if min_cell > 0:
        min_frame_ratio = min_frame_px / min_cell
        eff_frame_ratio = max(frame_ratio, min_frame_ratio)

    config.LOG.param("缝隙比例",
                     f"原始 {frame_ratio:.3f} → 有效 {eff_frame_ratio:.3f}")

    for r in range(grid_rows):
        for c in range(grid_cols):
            u0, u1 = c / grid_cols, (c + 1) / grid_cols
            v0, v1 = r / grid_rows, (r + 1) / grid_rows
            x00, y00 = _bil(u0, v0)
            x10, y10 = _bil(u1, v0)
            x11, y11 = _bil(u1, v1)
            x01, y01 = _bil(u0, v1)
            gx = (x00 + x10 + x11 + x01) / 4.0
            gy = (y00 + y10 + y11 + y01) / 4.0
            sh = 1.0 - eff_frame_ratio
            poly = [
                ((gx + (x00 - gx) * sh) * SSAA_INNER,
                 (gy + (y00 - gy) * sh) * SSAA_INNER),
                ((gx + (x10 - gx) * sh) * SSAA_INNER,
                 (gy + (y10 - gy) * sh) * SSAA_INNER),
                ((gx + (x11 - gx) * sh) * SSAA_INNER,
                 (gy + (y11 - gy) * sh) * SSAA_INNER),
                ((gx + (x01 - gx) * sh) * SSAA_INNER,
                 (gy + (y01 - gy) * sh) * SSAA_INNER),
            ]
            mdraw.polygon(poly, fill=255)

    mask_small = utils.downsample_lanczos(canvas, W, H)
    return np.asarray(mask_small, dtype=np.float32) / 255.0


# ═══════════════════════════════════════════════════════════════════
# 层 2：玻璃噪声
# ═══════════════════════════════════════════════════════════════════
def _apply_glass_material(mask, W, H, weather_type, cfg, seed, mult=1.0):
    rng = np.random.default_rng(seed)
    nl_a = cfg.get("glass_noise_low", 0.02) * mult
    nm_a = cfg.get("glass_noise_mid", 0.01) * mult
    nh_a = cfg.get("glass_noise_high", 0.005) * mult
    nl = utils.perlin_noise(W, H, 0.06, rng)
    nm = utils.perlin_noise(W, H, 0.02, rng)
    nh = utils.perlin_noise(W, H, 0.005, rng)
    m = 1.0 - nl_a * (1.0 - nl)
    m *= 1.0 - nm_a * (1.0 - nm)
    m *= 1.0 - nh_a * (1.0 - nh)
    return mask * m


# ═══════════════════════════════════════════════════════════════════
# 层 3：方向性透射
# ═══════════════════════════════════════════════════════════════════
def _apply_transmission_falloff(mask, W, H, cx, cy, radius, strength,
                                  direction="right"):
    """方向性衰减：靠窗户侧亮。"""
    if strength < 0.001:
        return mask
    yy, xx = np.mgrid[0:H, 0:W]
    cx_px = cx * W
    x_lo = cx_px - radius
    x_hi = cx_px + radius
    if x_hi - x_lo < 1:
        return mask
    t = np.clip((xx - x_lo) / (x_hi - x_lo), 0, 1)
    if direction == "left":
        t = 1.0 - t
    gradient = (1.0 - strength) + strength * t
    return mask * gradient


# ═══════════════════════════════════════════════════════════════════
# 层 4：窗框暗线
# ═══════════════════════════════════════════════════════════════════
def _apply_frame_dark_lines(mask, W, H, cfg, mult=1.0):
    """窗框投影：暗线（不是亮线）。"""
    frame_strength = cfg.get("patch_frame_scatter", 0.35) * mult
    if frame_strength <= 0:
        return mask
    if utils._HAS_CV2:
        arr_u8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
        gx = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 1, 0, ksize=3)
        gy = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 0, 1, ksize=3)
        edge = np.sqrt(gx * gx + gy * gy) / 1020.0
        edge = np.clip(edge, 0, 1)
    else:
        m_pil = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8),
                                 mode="L")
        edge = np.asarray(m_pil.filter(ImageFilter.FIND_EDGES),
                          dtype=np.float32) / 255.0
    return np.clip(mask * (1.0 - edge * frame_strength), 0, 1)


# ═══════════════════════════════════════════════════════════════════
# 层 5：污渍
# ═══════════════════════════════════════════════════════════════════
def _apply_smudges(mask, W, H, x0, y0, x1, y1, cfg, seed, count_override=None):
    count = (int(count_override) if count_override is not None
             else int(cfg.get("glass_smudge_count", 0)))
    smudge_size = cfg.get("glass_smudge_size", 0.006)
    if count <= 0: return mask
    rng = np.random.default_rng(seed)
    w_range = x1 - x0; h_range = y1 - y0
    if w_range < 20 or h_range < 20: return mask
    base_px = max(1, int(min(W, H) * smudge_size))
    dark = np.zeros((H, W), dtype=np.float32)
    for _ in range(count):
        cx = int(x0 + rng.random() * w_range)
        cy = int(y0 + rng.random() * h_range)
        r = max(1, int(base_px * (0.5 + rng.random())))
        s = 0.3 + 0.5 * rng.random()
        y_lo = max(0, cy - r); y_hi = min(H, cy + r + 1)
        x_lo = max(0, cx - r); x_hi = min(W, cx + r + 1)
        if y_hi <= y_lo or x_hi <= x_lo: continue
        yy, xx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(r, 1)
        circle = np.clip(1.0 - d, 0, 1) * s
        dark[y_lo:y_hi, x_lo:x_hi] = np.maximum(dark[y_lo:y_hi, x_lo:x_hi], circle)
    dark = utils.blur_2d(dark, max(1.0, base_px * 0.6))
    return mask * (1.0 - dark * 0.4)


# ═══════════════════════════════════════════════════════════════════
# 层 6：水痕
# ═══════════════════════════════════════════════════════════════════
def _apply_water_streaks(mask, W, H, x0, y0, x1, y1, cfg, seed,
                          count_override=None):
    count = (int(count_override) if count_override is not None
             else int(cfg.get("glass_water_streak_count", 0)))
    opacity = cfg.get("glass_water_streak_opacity", 0.15)
    if count <= 0: return mask
    rng = np.random.default_rng(seed)
    w_range = x1 - x0; h_range = y1 - y0
    if w_range < 20 or h_range < 20: return mask
    for _ in range(count):
        sx = int(x0 + rng.random() * w_range)
        sy = int(y0 + rng.random() * h_range * 0.25)
        length = int(h_range * (0.3 + rng.random() * 0.5))
        width = max(1, int(min(W, H) * 0.0015))
        drift = rng.normal(0, 1) * (w_range * 0.02)
        for t in range(length):
            yy = sy + t
            if yy >= H: break
            frac = t / max(length, 1)
            xx = int(sx + drift * frac + rng.normal(0, 0.4))
            xs_lo = max(0, xx - width); xs_hi = min(W, xx + width)
            if xs_hi <= xs_lo: continue
            fade = max(0.3, 1.0 - abs(frac - 0.5) * 1.0)
            mask[yy, xs_lo:xs_hi] *= (1.0 - opacity * fade)
    return mask


# ═══════════════════════════════════════════════════════════════════
# 层 7：焦散
# ═══════════════════════════════════════════════════════════════════
def _apply_caustics(mask, W, H, x0, y0, x1, y1, cfg, seed, mult=1.0):
    strength = cfg.get("glass_caustics_strength", 0.03) * mult
    if strength <= 0: return mask
    if utils._HAS_CV2:
        arr_u8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
        gx = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 1, 0, ksize=3)
        gy = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 0, 1, ksize=3)
        edge = np.sqrt(gx * gx + gy * gy) / 1020.0
        edge = np.clip(edge, 0, 1)
    else:
        m_pil = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8),
                                 mode="L")
        edge = np.asarray(m_pil.filter(ImageFilter.FIND_EDGES),
                          dtype=np.float32) / 255.0
    edge_blur = utils.blur_2d(edge, max(2.0, min(W, H) * 0.003))
    return np.clip(mask + edge_blur * strength, 0, 1)


# ═══════════════════════════════════════════════════════════════════
# 层 8：灰尘
# ═══════════════════════════════════════════════════════════════════
def _apply_dust_particles(mask, W, H, x0, y0, x1, y1, cfg, seed, mult=1.0):
    count = int(cfg.get("dust_particle_count", 15) * mult)
    size = cfg.get("dust_particle_size", 0.003)
    opacity = cfg.get("dust_particle_opacity", 0.15)
    if count <= 0: return mask
    rng = np.random.default_rng(seed)
    w_range = x1 - x0; h_range = y1 - y0
    if w_range < 20 or h_range < 20: return mask
    base_px = max(1, int(min(W, H) * size))
    bright = np.zeros((H, W), dtype=np.float32)
    for _ in range(count):
        cx = int(x0 + rng.random() * w_range)
        cy = int(y0 + rng.random() * h_range)
        r = max(1, int(base_px * (0.5 + rng.random())))
        s = opacity * (0.5 + rng.random())
        y_lo = max(0, cy - r); y_hi = min(H, cy + r + 1)
        x_lo = max(0, cx - r); x_hi = min(W, cx + r + 1)
        if y_hi <= y_lo or x_hi <= x_lo: continue
        yy, xx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(r, 1)
        circle = np.clip(1.0 - d, 0, 1) * s
        bright[y_lo:y_hi, x_lo:x_hi] = np.maximum(
            bright[y_lo:y_hi, x_lo:x_hi], circle)
    return np.clip(mask + bright, 0, 1)


# ═══════════════════════════════════════════════════════════════════
# 层 9：Bloom
# ═══════════════════════════════════════════════════════════════════
def _apply_bloom(mask, W, H, cfg, mult=1.0):
    s = cfg.get("patch_bloom_strength", 0.03) * mult
    if s <= 0: return mask
    ratio = cfg.get("bloom_radius_ratio", 0.010)
    radius = max(3.0, min(W, H) * ratio)
    high = np.clip(mask, 0, 1) ** 2
    bloom = utils.blur_2d(high, radius)
    return mask + bloom * s


# ═══════════════════════════════════════════════════════════════════
# 层 10：玻璃结构
# ═══════════════════════════════════════════════════════════════════
def _apply_glass_structure(mask, W, H, cfg, seed, cx, cy, w, h,
                            grid_rows, grid_cols):
    """玻璃结构 3 层：低频 + 每格 + 高频。"""
    rng = np.random.default_rng(seed)
    low_freq = utils.perlin_noise(W, H, 0.015, rng)
    mask = mask * (0.97 + 0.06 * low_freq)
    rng_cell = np.random.default_rng(seed + 1)
    for r in range(grid_rows):
        for c in range(grid_cols):
            u0, u1 = c / grid_cols, (c + 1) / grid_cols
            v0, v1 = r / grid_rows, (r + 1) / grid_rows
            cxs = max(0, int((cx - w / 2 + u0 * w) * W))
            cxe = min(W, int((cx - w / 2 + u1 * w) * W))
            cys = max(0, int((cy - h / 2 + v0 * h) * H))
            cye = min(H, int((cy - h / 2 + v1 * h) * H))
            if cxe <= cxs or cye <= cys:
                continue
            cell_factor = 0.98 + 0.04 * rng_cell.random()
            mask[cys:cye, cxs:cxe] *= cell_factor
    high_freq = utils.perlin_noise(W, H, 0.08, rng)
    mask = mask * (0.99 + 0.02 * high_freq)
    return mask


# ═══════════════════════════════════════════════════════════════════
# 层 11：墙面微凸起
# ═══════════════════════════════════════════════════════════════════
def _apply_wall_bump(mask, W, H, cfg, seed, strength=0.06):
    if strength <= 0:
        return mask
    rng = np.random.default_rng(seed)
    wall_bump = utils.perlin_noise(W, H, 0.03, rng)
    return mask * (1.0 - strength + 2.0 * strength * wall_bump)


# ═══════════════════════════════════════════════════════════════════
# 层 12：半影
# ═══════════════════════════════════════════════════════════════════
def _apply_penumbra(mask, W, H, penumbra_ratio, cfg):
    penumbra_width_px = penumbra_ratio * H
    divisor = float(cfg.get("penumbra_sigma_divisor", 1.5))
    sigma = penumbra_width_px / max(divisor, 0.5)
    max_ratio = cfg.get("penumbra_max_ratio", 0.015)
    sigma = min(sigma, H * max_ratio)
    config.LOG.param("半影",
                     f"宽度 {penumbra_width_px:.1f}px → σ={sigma:.2f}px")
    return utils.blur_2d(mask, max(0.5, sigma))


# ═══════════════════════════════════════════════════════════════════
# 层 13：菲涅尔边缘
# ═══════════════════════════════════════════════════════════════════
def _apply_fresnel_edge(mask, W, H, cfg, strength=0.10):
    if strength <= 0:
        return mask
    if utils._HAS_CV2:
        arr_u8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
        gx = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 1, 0, ksize=3)
        gy = utils.cv2.Sobel(arr_u8, utils.cv2.CV_32F, 0, 1, ksize=3)
        edge = np.sqrt(gx * gx + gy * gy) / 1020.0
        edge = np.clip(edge, 0, 1)
    else:
        m_pil = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8),
                                 mode="L")
        edge = np.asarray(m_pil.filter(ImageFilter.FIND_EDGES),
                          dtype=np.float32) / 255.0
    return np.clip(mask - edge * strength, 0, 1)


# ═══════════════════════════════════════════════════════════════════
# 层 14：光渗
# ═══════════════════════════════════════════════════════════════════
def _apply_halo(mask, W, H, cfg, strength=0.15):
    if strength <= 0:
        return mask
    r_small = max(2.0, min(W, H) * 0.008)
    r_large = max(5.0, min(W, H) * 0.025)
    halo_small = utils.blur_2d(mask, r_small)
    halo_large = utils.blur_2d(mask, r_large)
    outer_small = np.clip(halo_small - mask, 0, 1)
    outer_large = np.clip(halo_large - mask, 0, 1)
    halo = outer_small * 0.7 + outer_large * 0.3
    return np.clip(mask + halo * strength, 0, 1)


# ═══════════════════════════════════════════════════════════════════
# 层 15：年代感
# ═══════════════════════════════════════════════════════════════════
def _apply_aged(mask, W, H, cfg, seed, mult=1.0):
    if not cfg.get("aged_enabled", True):
        return mask
    rng = np.random.default_rng(seed)
    erode_amp = cfg.get("aged_erode", 0.001)
    noise_amp = cfg.get("aged_noise", 0.04) * mult
    spots_d = cfg.get("aged_dark_spots", 0.0003)
    fbm = utils.fbm_noise(W, H, octaves=4, base_scale=0.006, rng=rng)
    mask = mask * (1.0 - noise_amp * (1.0 - fbm))
    er = max(1, int(H * erode_amp))
    arr_u8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
    if utils._HAS_CV2:
        ksize = max(3, 2 * er + 1)
        kernel = utils.cv2.getStructuringElement(utils.cv2.MORPH_ELLIPSE,
                                                  (ksize, ksize))
        eroded_u8 = utils.cv2.erode(arr_u8, kernel)
        e_np = eroded_u8.astype(np.float32) / 255.0
    else:
        eroded = Image.fromarray(arr_u8, mode="L")
        for _ in range(er):
            eroded = eroded.filter(ImageFilter.MinFilter(3))
        e_np = np.asarray(eroded, dtype=np.float32) / 255.0
    edge = np.clip(mask - e_np, 0, 1)
    mask = np.clip(mask - edge * 0.15, 0, 1)
    total = int(W * H * spots_d)
    if total > 0:
        xs = rng.integers(0, W, size=total)
        ys = rng.integers(0, H, size=total)
        for x, y in zip(xs, ys):
            y_lo, y_hi = max(0, y - 1), min(H, y + 2)
            x_lo, x_hi = max(0, x - 1), min(W, x + 2)
            mask[y_lo:y_hi, x_lo:x_hi] *= 0.85
    return mask


# ═══════════════════════════════════════════════════════════════════
# 雨天 / 雪天（弥散分支用）
# ═══════════════════════════════════════════════════════════════════
def _apply_rain_droplets(mask, W, H, x0, y0, x1, y1, cfg, seed):
    rng = np.random.default_rng(seed)
    count = int(cfg.get("rain_droplet_count", 15))
    length = cfg.get("rain_droplet_length", 0.15)
    opacity = cfg.get("rain_droplet_opacity", 0.40)
    h_range = y1 - y0; w_range = x1 - x0
    if h_range < 10 or w_range < 10: return mask
    for _ in range(count):
        cx = int(x0 + rng.random() * w_range)
        cy = int(y0 + rng.random() * h_range)
        dl = int(h_range * length * (0.5 + rng.random()))
        th = max(1, int(min(w_range, h_range) * 0.008))
        y_lo = max(0, cy); y_hi = min(H, cy + dl)
        x_lo = max(0, cx - th); x_hi = min(W, cx + th)
        if y_hi <= y_lo or x_hi <= x_lo: continue
        mask[y_lo:y_hi, x_lo:x_hi] *= (1.0 - opacity)
    return mask


def _apply_snow_flakes(mask, W, H, x0, y0, x1, y1, cfg, seed):
    rng = np.random.default_rng(seed)
    count = int(cfg.get("snow_flake_count", 40))
    flake_size = cfg.get("snow_flake_size", 0.008)
    h_range = y1 - y0; w_range = x1 - x0
    if h_range < 10 or w_range < 10: return mask
    flake_px = max(1, int(min(W, H) * flake_size))
    for _ in range(count):
        cx = int(x0 + rng.random() * w_range)
        cy = int(y0 + rng.random() * h_range)
        y_lo = max(0, cy - flake_px); y_hi = min(H, cy + flake_px)
        x_lo = max(0, cx - flake_px); x_hi = min(W, cx + flake_px)
        if y_hi <= y_lo or x_hi <= x_lo: continue
        mask[y_lo:y_hi, x_lo:x_hi] = np.clip(
            mask[y_lo:y_hi, x_lo:x_hi] + 0.3, 0, 1)
    return mask


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════
def render_light_patch(W: int, H: int, light, weather,
                       window_orientation="right",
                       window_scale=0.50,
                       grid_rows=3, grid_cols=2,
                       grid_frame_ratio=0.18,
                       R_clean=None,
                       progress=None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    光斑 mask（含材质 + 玻璃 + 光渗）。
    返回 (mask, meta)。
    """
    cfg = config.get_lighting()
    wt = weather.weather_type
    profiles = cfg.get("weather_profile", {})
    prof = profiles.get(wt, profiles.get("cloudy", {}))

    noise_mult      = float(prof.get("noise_mult", 1.0))
    trans_mult      = float(prof.get("transmission_mult", 1.0))
    scatter_mult    = float(prof.get("scatter_mult", 1.0))
    bloom_mult      = float(prof.get("bloom_mult", 1.0))
    dust_mult       = float(prof.get("dust_mult", 1.0))
    caustics_mult   = float(prof.get("caustics_mult", 1.0))
    aged_mult       = float(prof.get("aged_mult", 1.0))
    smudge_abs      = prof.get("smudge_abs", None)
    water_abs       = prof.get("water_abs", None)
    kill_grid       = bool(prof.get("kill_grid", False))

    rep = utils.report
    empty = {"cx": 0.0, "cy": 0.0, "size": 0, "irradiance": 0.0,
             "weather_type": wt, "mode": "none"}

    if light.irradiance < 0.0005:
        return np.zeros((H, W), dtype=np.float32), empty

    cx = light.patch_center_x
    cy = light.patch_center_y
    w = max(0.1, min(1.2, light.patch_width * window_scale * 2.0))
    h = max(0.1, min(1.2, light.patch_height * window_scale * 2.0))
    shear_x = light.patch_shear_x

    x0 = max(0, int((cx - w / 2) * W))
    x1 = min(W, int((cx + w / 2) * W))
    y0 = max(0, int((cy - h / 2) * H))
    y1 = min(H, int((cy + h / 2) * H))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((H, W), dtype=np.float32), empty

    # ══════════ 弥散分支 ══════════
    if kill_grid or wt in ("overcast", "rain", "haze"):
        rep(progress, 0.10, "椭圆距离场")
        yy, xx = np.mgrid[0:H, 0:W]
        hw = max(1.0, w * W / 2.0); hh = max(1.0, h * H / 2.0)
        dist = np.sqrt(((xx - cx * W) / hw) ** 2 +
                       ((yy - cy * H) / hh) ** 2)
        mask = np.clip(1.0 - dist, 0, 1)
        rep(progress, 0.40, "弥散模糊")
        blur_r = min(W, H) * 0.08 * cfg.get("overcast_blur_mult", 3.0)
        if wt == "rain": blur_r *= 1.8
        elif wt == "haze": blur_r *= cfg.get("haze_blur_mult", 2.0)
        mask = utils.blur_2d(mask, blur_r)
        rep(progress, 0.75)
        if wt == "rain":
            rep(progress, 0.80, "雨天水痕")
            mask = _apply_rain_droplets(mask, W, H, x0, y0, x1, y1, cfg,
                                         utils.stable_seed(cx, cy, "rain"))
        if wt == "snow":
            rep(progress, 0.85, "雪花")
            mask = _apply_snow_flakes(mask, W, H, x0, y0, x1, y1, cfg,
                                       utils.stable_seed(cx, cy, "snow"))
        mask = np.clip(mask, 0, 1)
        rep(progress, 1.00)
        return mask, {"cx": cx, "cy": cy, "size": w * W,
                      "irradiance": light.irradiance,
                      "weather_type": wt, "mode": "diffuse"}

    # ══════════ 窗格分支 ══════════
    ssaa = int(cfg.get("patch_ssaa", 3))
    min_frame_px = float(cfg.get("grid_min_frame_px", 5.0))
    seed_grid = utils.stable_seed(cx, cy, grid_rows, grid_cols, "grid")

    rep(progress, 0.02, "绘制窗格 mask")
    mask = _render_parallelogram_grid(W, H, cx, cy, w, h, shear_x,
                                       grid_rows, grid_cols,
                                       grid_frame_ratio, ssaa=ssaa,
                                       min_frame_px=min_frame_px)

    rep(progress, 0.08, "玻璃噪声")
    mask = _apply_glass_material(mask, W, H, wt, cfg, seed_grid,
                                  mult=noise_mult)

    rep(progress, 0.14, "方向性透射")
    trans_strength = float(cfg.get("transmission_strength", 0.20)) * trans_mult
    mask = _apply_transmission_falloff(mask, W, H, cx, cy,
                                        w * W * 0.6, trans_strength,
                                        direction=window_orientation)

    rep(progress, 0.20, "窗框暗线")
    mask = _apply_frame_dark_lines(mask, W, H, cfg, mult=scatter_mult)

    smudge_count = (int(smudge_abs) if smudge_abs is not None
                    else int(cfg.get("glass_smudge_count", 0)))
    if smudge_count > 0:
        rep(progress, 0.26, f"污渍 {smudge_count}")
        mask = _apply_smudges(mask, W, H, x0, y0, x1, y1, cfg,
                              utils.stable_seed(cx, cy, "smudge"),
                              count_override=smudge_count)

    water_count = (int(water_abs) if water_abs is not None
                   else int(cfg.get("glass_water_streak_count", 0)))
    if water_count > 0:
        rep(progress, 0.32, f"水痕 {water_count}")
        mask = _apply_water_streaks(mask, W, H, x0, y0, x1, y1, cfg,
                                     utils.stable_seed(cx, cy, "water"),
                                     count_override=water_count)

    rep(progress, 0.40, "焦散")
    mask = _apply_caustics(mask, W, H, x0, y0, x1, y1, cfg,
                           utils.stable_seed(cx, cy, "caustics"),
                           mult=caustics_mult)

    rep(progress, 0.48, "灰尘粒子")
    mask = _apply_dust_particles(mask, W, H, x0, y0, x1, y1, cfg,
                                 utils.stable_seed(cx, cy, "dust"),
                                 mult=dust_mult)

    rep(progress, 0.56, "Bloom")
    mask = _apply_bloom(mask, W, H, cfg, mult=bloom_mult)

    rep(progress, 0.64, "玻璃结构")
    mask = _apply_glass_structure(mask, W, H, cfg,
                                   utils.stable_seed(cx, cy, "struct"),
                                   cx, cy, w, h, grid_rows, grid_cols)

    if R_clean is not None:
        cracks_strength = float(cfg.get("cracks_strength", 0.5))
        if cracks_strength > 0:
            rep(progress, 0.70, "材质裂纹内渗")
            # 委托给 retinex 模块（保持本文件独立，不直接 import）
            # 由 pipeline 在调用前先算好 material 裂纹 mask 更好
            # 这里保持简单：只做 mask * (1 - cracks * strength)
            lum = R_clean.mean(axis=2)
            median = utils.median_filter_2d(lum, 5)
            cracks = np.clip(median - lum, 0, 1)
            cracks = np.clip(cracks * 3.0, 0, 1)
            mask = mask * (1.0 - cracks * cracks_strength)

    wall_bump = float(cfg.get("wall_bump_strength", 0.06))
    if wall_bump > 0:
        rep(progress, 0.76, "墙面微凸起")
        mask = _apply_wall_bump(mask, W, H, cfg,
                                 utils.stable_seed(cx, cy, "wallbump"),
                                 strength=wall_bump)

    rep(progress, 0.80, "半影")
    mask = _apply_penumbra(mask, W, H, light.penumbra_ratio, cfg)

    fresnel = float(cfg.get("fresnel_strength", 0.10))
    if fresnel > 0:
        rep(progress, 0.84, "菲涅尔边缘")
        mask = _apply_fresnel_edge(mask, W, H, cfg, strength=fresnel)

    halo_strength = float(cfg.get("halo_strength", 0.15))
    if halo_strength > 0:
        rep(progress, 0.88, "光渗")
        mask = _apply_halo(mask, W, H, cfg, strength=halo_strength)

    rep(progress, 0.92, "玻璃年代感")
    mask = _apply_aged(mask, W, H, cfg,
                       utils.stable_seed(cx, cy, "aged"),
                       mult=aged_mult)

    mask = np.clip(mask, 0, 1)
    rep(progress, 1.00)
    return mask, {"cx": cx, "cy": cy, "size": w * W,
                  "irradiance": light.irradiance,
                  "weather_type": wt, "mode": "grid"}