#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — 文字渲染

职责：
  1. 文字 SSAA（全域超采样）
  2. 智能断行 + 位置计算
  3. 年代感处理（含材质耦合）
  4. 接触阴影
  5. 物理光学融合（朱红颜料）

不 import 本框架其他文件。
只 import config + utils（本框架）+ 标准库 + numpy + PIL。
被 pipeline.py 编排调用。
"""
import gc
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 文字位置
# ═══════════════════════════════════════════════════════════════════
def _compute_text_position(cw, ch, tw, th, anchor="center",
                            px=50.0, py=50.0):
    px = max(0.0, min(100.0, px)) / 100.0
    py = max(0.0, min(100.0, py)) / 100.0
    ax, ay = cw * px, ch * py
    if anchor == "tl": x, y = ax, ay
    elif anchor == "tr": x, y = ax - tw, ay
    elif anchor == "bl": x, y = ax, ay - th
    elif anchor == "br": x, y = ax - tw, ay - th
    elif anchor == "tc": x, y = ax - tw / 2, ay
    elif anchor == "bc": x, y = ax - tw / 2, ay - th
    elif anchor == "lc": x, y = ax, ay - th / 2
    elif anchor == "rc": x, y = ax - tw, ay - th / 2
    else: x, y = ax - tw / 2, ay - th / 2
    return int(round(x)), int(round(y))


# ═══════════════════════════════════════════════════════════════════
# 渐进降采样（PIL LANCZOS，保留字形锐度）
# ═══════════════════════════════════════════════════════════════════
def _progressive_downsample_L(img, tw, th):
    while img.width > tw * 2 and img.height > th * 2:
        img = img.resize((max(tw, img.width // 2), max(th, img.height // 2)),
                         config.RESAMPLE_LANCZOS)
    if img.width != tw or img.height != th:
        img = img.resize((tw, th), config.RESAMPLE_LANCZOS)
    return img


# ═══════════════════════════════════════════════════════════════════
# SSAA 文字 alpha
# ═══════════════════════════════════════════════════════════════════
def render_text_alpha_L(text, font_path, cw, ch,
                         font_ratio=0.18, ssaa=8, font_pos=None,
                         progress=None, stage_offset=0):
    """
    在 ssaa 倍大画布上绘制文字，渐进降采样到 (cw, ch)。
    带进度汇报（子阶段 2.1 ~ 2.5）。
    """
    rep = utils.report
    ssaa = max(1, min(config.MAX_SSAA, int(ssaa)))
    BW, BH = cw * ssaa, ch * ssaa
    fp = font_pos or {}
    anchor = fp.get("anchor", config.DEFAULT_ANCHOR)
    px = fp.get("x", config.DEFAULT_POS_X)
    py = fp.get("y", config.DEFAULT_POS_Y)
    if anchor not in config.ANCHORS:
        anchor = config.DEFAULT_ANCHOR

    # 2.1 分配大画布
    rep(progress, 0.05, f"分配大画布 {BW}x{BH}")
    try:
        big = Image.new("L", (BW, BH), 0)
    except (MemoryError, OSError) as e:
        raise RuntimeError(f"分配大画布失败: {e}")

    # 2.2 加载字体
    max_px = 16384
    fsize = max(4, min(max_px, int(ch * font_ratio * ssaa)))
    rep(progress, 0.15, f"加载字体 size={fsize}")
    font = config.load_font(font_path, fsize)

    # 2.3 智能断行
    lines = config.smart_split_text(text)
    rep(progress, 0.25, f"断行 {len(lines)} 行")

    # 2.4 计算文字块
    mdraw = ImageDraw.Draw(Image.new("L", (1, 1)))
    dims = []
    max_w = 0
    total_h = 0
    gap = max(1, int(fsize * 0.15))
    for line in lines:
        bb = mdraw.textbbox((0, 0), line, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        dims.append((bb, w, h))
        max_w = max(max_w, w)
        total_h += h + gap
    if lines:
        total_h -= gap
    rep(progress, 0.40, f"文字块 {max_w}x{total_h}")

    # 2.5 绘制
    bd = ImageDraw.Draw(big)
    tx, ty = _compute_text_position(BW, BH, max_w, total_h, anchor, px, py)
    y = ty
    for line, (bb, w, h) in zip(lines, dims):
        x = tx + (max_w - w) // 2 - bb[0]
        bd.text((x, y - bb[1]), line, font=font, fill=255)
        y += h + gap
    rep(progress, 0.75, "绘制完成")

    # 2.6 渐进降采样
    small = _progressive_downsample_L(big, cw, ch)
    del big
    gc.collect()
    rep(progress, 1.00, "SSAA 完成")
    return small


# ═══════════════════════════════════════════════════════════════════
# 年代感 alpha
# ═══════════════════════════════════════════════════════════════════
def generate_aged_alpha(alpha, W, H, seed=None, params=None,
                         material_map=None, material_strength=0.4,
                         progress=None):
    """
    年代感 alpha 处理（含材质耦合）。
      - 多层噪声调制
      - 边缘侵蚀
      - 颜料扩散
      - 氧化颗粒
      - 材质耦合：字体在不同材质区域透明度略有差异
    """
    rep = utils.report
    p = params or {}
    low_a  = p.get("noise_low", config.TEXT_NOISE_LOW_AMP)
    mid_a  = p.get("noise_mid", config.TEXT_NOISE_MID_AMP)
    high_a = p.get("noise_high", config.TEXT_NOISE_HIGH_AMP)
    diff_a = p.get("diffusion", config.DIFFUSION_AMP)
    ox_d   = p.get("oxidation", config.OXIDATION_DOTS)
    ox_a   = p.get("oxidation_amp", config.OXIDATION_AMP)

    rng = np.random.default_rng(seed)

    # 4.1 生成噪声
    rep(progress, 0.10, "生成噪声")
    nl = utils.perlin_noise(W, H, config.TEXT_NOISE_LOW_SCALE, rng)
    nm = utils.perlin_noise(W, H, config.TEXT_NOISE_MID_SCALE, rng)
    nh = utils.perlin_noise(W, H, config.TEXT_NOISE_HIGH_SCALE, rng)

    # 4.2 噪声扰动
    rep(progress, 0.30, "噪声扰动")
    a = alpha * (1.0 - low_a * (1.0 - nl))
    a = a * (1.0 - mid_a * (1.0 - nm))
    del nl, nm
    gc.collect()

    # 4.3 材质耦合（默认关闭：参考实现无此步，开启会让字形随材质斑驳）
    if material_map is not None and material_strength > 0.0:
        rep(progress, 0.42, "材质耦合")
        mat_factor = 1.0 + (material_map - 1.0) * material_strength
        a = np.clip(a * mat_factor, 0.0, 1.0)

    # 4.4 边缘毛糙
    rep(progress, 0.50, "边缘毛糙")
    a_pil = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), mode="L")
    er = max(1, int(H * config.EDGE_ERODE_RATIO))
    eroded = a_pil
    for _ in range(er):
        eroded = eroded.filter(ImageFilter.MinFilter(3))
    e_np = np.asarray(eroded, dtype=np.float32) / 255.0
    del eroded
    edge = np.clip(a - e_np, 0.0, 1.0)
    del e_np
    perturb = (nh - 0.5) * 2.0 * high_a
    a = np.clip(a + edge * perturb, 0.0, 1.0)
    del perturb, edge, nh, a_pil

    # 4.5 颜料扩散
    rep(progress, 0.70, "颜料扩散")
    dr = max(1, int(H * config.DIFFUSION_RATIO))
    dp = Image.fromarray((a * 255).astype(np.uint8), mode="L")
    dp = dp.filter(ImageFilter.GaussianBlur(dr))
    diff = np.asarray(dp, dtype=np.float32) / 255.0
    del dp
    diff = np.clip(diff - a, 0.0, 1.0) * diff_a
    a = np.clip(a + diff, 0.0, 1.0)
    del diff
    gc.collect()

    # 4.6 氧化颗粒
    rep(progress, 0.88, "氧化颗粒")
    total = int(W * H * ox_d)
    if total > 0:
        xs = rng.integers(0, W, size=total)
        ys = rng.integers(0, H, size=total)
        mask = a[ys, xs] > 0.1
        xs, ys = xs[mask], ys[mask]
        for x, y in zip(xs, ys):
            y0, y1 = max(0, y - 1), min(H, y + 2)
            x0, x1 = max(0, x - 1), min(W, x + 2)
            a[y0:y1, x0:x1] *= (1.0 - ox_a * 0.5)

    rep(progress, 1.00, "年代感完成")
    return a


# ═══════════════════════════════════════════════════════════════════
# 接触阴影
# ═══════════════════════════════════════════════════════════════════
def _compute_contact_shadow(alpha, W, H, light, cfg,
                              progress=None):
    """
    接触阴影：基于光照方向偏移。
    返回 occ (H, W) float32。
    """
    rep = utils.report
    if light:
        s_dx = light.shadow_dx
        s_dy = light.shadow_dy
    else:
        s_dx = 0.0
        s_dy = config.SHADOW_LEN_MAX * 0.5

    blur_px = max(1, int(H * config.SHADOW_BLUR_RATIO))
    off_x = int(round(H * s_dx))
    off_y = int(round(H * s_dy))
    max_off = int(H * config.SHADOW_LEN_MAX)
    off_x = max(-max_off, min(max_off, off_x))
    off_y = max(-max_off, min(max_off, off_y))

    # 5.1 膨胀
    rep(progress, 0.25, f"膨胀 blur={blur_px}px")
    a_pil = Image.fromarray((alpha * 255).astype(np.uint8), mode="L")
    dil = a_pil
    for _ in range(max(1, blur_px)):
        dil = dil.filter(ImageFilter.MaxFilter(3))
    d_np = np.asarray(dil, dtype=np.float32) / 255.0
    del dil, a_pil

    # 5.2 取边缘
    rep(progress, 0.50, "提取轮廓")
    sr = np.clip(d_np - alpha, 0.0, 1.0)
    del d_np

    # 5.3 偏移
    rep(progress, 0.65, f"偏移 ({off_x:+d},{off_y:+d})")
    sh = utils.shift_array_2d(sr, off_x, off_y)
    del sr

    # 5.4 模糊
    rep(progress, 0.85, "模糊")
    sp = Image.fromarray((sh * 255).astype(np.uint8), mode="L")
    del sh
    sp = sp.filter(ImageFilter.GaussianBlur(blur_px))
    occ = np.asarray(sp, dtype=np.float32) / 255.0
    del sp
    gc.collect()

    rep(progress, 1.00, "阴影完成")
    return occ


# ═══════════════════════════════════════════════════════════════════
# 融合主流程
# ═══════════════════════════════════════════════════════════════════
def fuse(image_path, text, font_path,
         ssaa=8, font_ratio=0.18, seed=None,
         render_params=None, font_pos=None, light=None,
         progress=None, stage_offset=0,
         material_map=None):
    """
    文字叠字融合。
    返回输出 PNG 路径。

    子阶段：
      [1] 读取底图
      [2] 文字超采样（含断行 / 字体 / 绘制 / 降采样）
      [3] 年代感处理（含材质耦合）
      [4] 接触阴影
      [5] 物理光学合成
      [6] 线性编码
      [7] 保存
    """
    rp = render_params or {}
    cinnabar = rp.get("cinnabar", config.CINNABAR_REFLECTANCE)
    aged = rp.get("aged", {})
    shadow_strength = rp.get("shadow_strength", config.SHADOW_STRENGTH)

    if progress is not None:
        if not progress.stages:
            progress.set_stages([
                "读取底图",
                "文字超采样",
                "年代感处理",
                "接触阴影",
                "物理合成",
                "线性编码",
                "保存",
            ])
        if progress.current_stage < 0:
            progress.set_stage(0 + stage_offset)

    try:
        # ══════════ [1] 读取底图 ══════════
        base = Image.open(image_path).convert("RGB")
        W, H = base.size
        base_srgb = np.asarray(base, dtype=np.float32) / 255.0
        if progress is not None:
            progress.log(f"底图 {W}x{H}")
            progress.set_stage(1 + stage_offset)

        # ══════════ [2] 文字超采样 ══════════
        text_l = render_text_alpha_L(
            text, font_path, W, H,
            font_ratio, ssaa, font_pos,
            progress=progress, stage_offset=stage_offset)
        alpha_raw = np.asarray(text_l, dtype=np.float32) / 255.0
        del text_l
        gc.collect()
        if progress is not None:
            progress.set_stage(2 + stage_offset)

        # ══════════ [3] 年代感处理 ══════════
        alpha = generate_aged_alpha(
            alpha_raw, W, H, seed=seed, params=aged,
            material_map=material_map,
            material_strength=config.TEXT_MATERIAL_COUPLING,
            progress=progress)
        del alpha_raw
        gc.collect()
        if progress is not None:
            progress.set_stage(3 + stage_offset)

        # ══════════ [4] 接触阴影 ══════════
        occ = _compute_contact_shadow(
            alpha, W, H, light, config.get_lighting(),
            progress=progress)
        if progress is not None:
            progress.set_stage(4 + stage_offset)

        # ══════════ [5] 物理光学合成 ══════════
        if progress is not None:
            progress.set_progress(0.20)
        base_lin = utils.srgb_to_linear(base_srgb)
        del base_srgb
        if progress is not None:
            progress.set_progress(0.40)
        L_eff = base_lin * (1.0 - occ[..., None] * shadow_strength)
        del base_lin, occ
        if progress is not None:
            progress.set_progress(0.60)
        a3 = alpha[..., None]
        rho = (1.0 - a3) + a3 * cinnabar[None, None, :]
        del a3
        if progress is not None:
            progress.set_progress(0.80)
        L_out = L_eff * rho
        del L_eff, rho, alpha
        if progress is not None:
            progress.set_progress(1.00)
            progress.set_stage(5 + stage_offset)

        # ══════════ [6] 线性编码 ══════════
        fs = utils.linear_to_srgb(L_out)
        del L_out
        fu8 = (fs * 255).astype(np.uint8)
        del fs
        if progress is not None:
            progress.set_stage(6 + stage_offset)

        # ══════════ [7] 保存 ══════════
        out = Image.fromarray(fu8)
        del fu8
        out_path = image_path.with_name(
            image_path.stem.replace("_lit", "").replace("_raw", "")
            + "_final.png")
        out.save(out_path)
        if progress is not None:
            progress.set_progress(1.0)
            progress.finish()
        return out_path

    except Exception as e:
        import traceback
        config.LOG.error(traceback.format_exc())
        if progress is not None:
            progress.finish()
        raise RuntimeError(f"文字叠字失败: {e}")