#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — AI 模式编排

职责：
  Token → 时间/位置/天气 → 光照 → 提示词 → API → 底图 → 材质反推 → 叠字

进度风格与离线模式统一：
  [1] 准备（Token / 尺寸 / 时间 / 位置 / 天气 / 光照）  交互式，无进度条
  [2] 提示词构建（快速）
  [3] API 请求（Spinner）
  [4] 底图写入（ProgressBar）
  [5] 材质反推（GlobalProgress）
  [6] 文字叠字（GlobalProgress，7 阶段）

本文件是编排层，可 import 跨框架。
"""
import base64
import threading
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

import config
import frame_light
import frame_render
from . import utils as u
from . import progress as prog
from .offline import (
    resolve_time, resolve_location, resolve_weather,
    pick_text, pick_font_and_pos, build_render_params,
    confirm_render,
)


# ═══════════════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════════════
def call_agnes_api(token, prompt, size):
    """调用 Agnes API，返回 b64 字符串或 None。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.AGNES_MODEL,
        "prompt": prompt,
        "size": size,
        "extra_body": {"response_format": "b64_json"},
    }

    spinner = prog.Spinner(label="请求 API")
    stop = threading.Event()

    def tick():
        while not stop.is_set():
            spinner.tick()
            time.sleep(0.1)

    t = threading.Thread(target=tick, daemon=True)
    t.start()
    t0 = time.time()

    try:
        r = requests.post(config.AGNES_API_URL, headers=headers,
                          json=payload, timeout=300)
        stop.set()
        t.join(timeout=1.0)
        spinner.stop("API 返回")
    except requests.exceptions.RequestException as e:
        stop.set()
        t.join(timeout=1.0)
        spinner.stop()
        u.err(f"网络异常: {e}")
        return None

    config.LOG.timing("API 请求", t0)

    if r.status_code != 200:
        u.err(f"API {r.status_code}: {r.text[:200]}")
        return None

    try:
        data = r.json()
    except ValueError:
        u.err("API 返回非 JSON")
        return None

    items = data.get("data", [])
    if not items:
        u.err("API 返回数据为空")
        return None

    item = items[0]
    if "b64_json" in item:
        return item["b64_json"]
    if "url" in item:
        try:
            resp = requests.get(item["url"], timeout=180)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode()
        except requests.exceptions.RequestException as e:
            u.err(f"图片下载失败: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════
# 材质反推
# ═══════════════════════════════════════════════════════════════════
def _extract_material_from_ai_image(image_path: Path, progress=None):
    """
    从 AI 生成的底图反推材质图（用于叠字耦合）。
    带进度汇报（4 子阶段）。
    """
    rep = frame_render.utils.report
    try:
        from frame_render import retinex, material as mat_mod
        from frame_render.utils import srgb_to_linear

        rep(progress, 0.10, "读取底图")
        img = Image.open(image_path).convert("RGB")
        W, H = img.size

        # 缩到工作尺寸
        MAX_WORK = 1024
        if max(W, H) > MAX_WORK:
            scale = MAX_WORK / max(W, H)
            img_small = img.resize((int(W * scale), int(H * scale)),
                                    config.RESAMPLE_BILINEAR)
        else:
            img_small = img

        rep(progress, 0.25, "Retinex 分解")
        wall_srgb = np.asarray(img_small, dtype=np.float32) / 255.0
        wall_lin = srgb_to_linear(wall_srgb)

        cfg = config.get_lighting()
        R_clean, _, _ = retinex.decompose_albedo(wall_lin, cfg, progress=None)

        rep(progress, 0.60, "材质提取")
        mat_obj = mat_mod.extract_material(R_clean, cfg, progress=None)

        rep(progress, 0.85, "上采样")
        m = mat_obj.albedo.mean(axis=2)
        if m.shape != (H, W):
            m_pil = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8),
                                     mode="L")
            m_pil = m_pil.resize((W, H), config.RESAMPLE_BILINEAR)
            m = np.asarray(m_pil, dtype=np.float32) / 255.0

        rep(progress, 1.00, "材质反推完成")
        return m.astype(np.float32)
    except Exception as e:
        config.LOG.warn(f"AI 底图材质反推失败: {e}")
        rep(progress, 1.00, f"材质反推失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════
def run_ai_generate(args, interactive=True) -> int:
    defaults = config.get_defaults()

    # ══════════════════════════════════════════════════════════
    # [1] 准备阶段（交互式，无进度条）
    # ══════════════════════════════════════════════════════════
    # Token
    token = config.resolve_token(args.token)
    if not token:
        u.warn("未找到 API Token")
        if interactive and u.ask_yn("进入设置？", "y"):
            from . import settings as st
            st.settings_credentials()
            token = config.resolve_token(None)
            if not token:
                u.err("Token 仍未设置")
                return 1
        else:
            u.err("需要 --token 或配置")
            return 1
    else:
        u.ok(f"Token {_mask(token)}")

    # 尺寸
    result = _resolve_output_size(args, defaults, interactive)
    if result is None:
        return 1
    api_size, res, asp = result

    # 时间
    local_time = resolve_time(args, interactive)
    if local_time is None:
        return 1

    # 位置
    _loc = resolve_location(args, interactive)
    if _loc is None:
        u.err("位置解析失败")
        return 1
    lat, lon, city, _ = _loc

    # 天气
    weather, _ = resolve_weather(args, lat, lon, interactive)

    # 光照
    u.h("光照参数")
    win_side = (args.window_orientation
                or defaults.get("window_orientation", "right"))
    light = frame_light.compute_light(
        lat, lon, local_time, weather,
        window_orientation=win_side,
        shadow_length=args.shadow_length or "auto")

    u.field("主光源", light.source)
    u.field("方位角", f"{light.az:+.2f}°")
    u.field("高度角", f"{light.alt:+.2f}°")
    u.field("辐照度", f"{light.irradiance:.4f}")
    u.field("描述", light.description)
    if light.visibility_reason:
        u.field("可达性", light.visibility_reason)

    # 光照级别
    if args.light_level is not None:
        light_lv = args.light_level
        u.ok(f"强制级别 {light_lv}")
    else:
        light_lv = frame_light.classify_light_auto(local_time, light)
        u.ok(f"自动级别 {light_lv}")

    # 窗户几何
    u.h("窗户参数")
    grid_rows = (args.grid_rows if args.grid_rows is not None
                 else defaults.get("grid_rows", 3))
    grid_cols = (args.grid_cols if args.grid_cols is not None
                 else defaults.get("grid_cols", 2))
    u.field("窗户位置", win_side)
    u.field("窗格", f"{grid_rows} x {grid_cols}")

    # 墙面
    u.h("墙面描述")
    prompts = config.get_prompts()
    if args.wall_desc:
        wall_desc = args.wall_desc
        u.ok("命令行指定")
    elif interactive:
        u.field("默认", u.trunc(prompts["wall"], 50))
        raw = u.ask("使用默认? [y=使用 / 自定义]", "y").strip()
        wall_desc = prompts["wall"] if raw.lower() in ("y", "yes", "") else raw
    else:
        wall_desc = prompts["wall"]
        u.ok("使用默认")

    # 文字 / 字体 / 精度
    text = pick_text(args, interactive)
    font, font_pos = pick_font_and_pos(args, defaults, interactive)
    if font is None:
        return 1

    u.h("渲染精度")
    ssaa = max(1, min(config.MAX_SSAA,
                       int(args.ssaa if args.ssaa is not None
                           else defaults["ssaa"])))
    fr = (args.font_ratio if args.font_ratio is not None
          else defaults["font_ratio"])
    u.field("超采样", f"{ssaa}x")
    u.field("字体比例", f"{fr:.3f}")

    if args.dry_run:
        u.h("Dry Run")
        u.info("未发送 API")
        return 0

    out_dir = Path(args.output) if args.output else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = local_time.strftime("%Y%m%d_%H%M%S")
    prefix = args.output_name or "AI"

    # ══════════════════════════════════════════════════════════
    # [2] 提示词构建
    # ══════════════════════════════════════════════════════════
    u.h("提示词构建")
    prompt = frame_light.build_base_prompt(
        asp if asp in config.ASPECT_RATIOS else "16:9",
        light_lv, wall_desc, light, prompts,
        grid_rows=grid_rows, grid_cols=grid_cols)

    if args.verbose:
        print()
        for line in prompt.split("\n"):
            print(f"    {line}")

    config.LOG.debug("=== AI 提示词开始 ===")
    for line in prompt.split("\n"):
        config.LOG.debug(f"  {line}")
    config.LOG.debug("=== AI 提示词结束 ===")
    u.ok(f"提示词 {len(prompt)} 字符")

    # ══════════════════════════════════════════════════════════
    # [3] API 请求
    # ══════════════════════════════════════════════════════════
    u.h("生成 AI 底图")
    b64 = call_agnes_api(token, prompt, api_size)
    if not b64:
        u.err("底图生成失败")
        return 1

    # ══════════════════════════════════════════════════════════
    # [4] 底图写入
    # ══════════════════════════════════════════════════════════
    raw_path = out_dir / f"{prefix}_{stamp}_raw.png"
    rb = base64.b64decode(b64)
    total = len(rb)
    with prog.ProgressBar(total=total, label="写入") as pb:
        with open(raw_path, "wb") as f:
            chunk = max(64 * 1024, total // 50)
            for i in range(0, total, chunk):
                f.write(rb[i:i + chunk])
                pb.update(min(chunk, total - i))
    u.ok(f"{raw_path.name} ({total / 1024:.1f} KB)")

    if args.no_render:
        u.h("跳过文字叠字")
        u.info(f"AI 底图已保存: {raw_path.name}")
        return 0

    # ══════════════════════════════════════════════════════════
    # [5] 材质反推
    # ══════════════════════════════════════════════════════════
    u.h("材质反推")
    progress_mat = prog.GlobalProgress(enabled=interactive)
    progress_mat.set_stages([
        "读取底图",
        "Retinex 分解",
        "材质提取",
        "上采样",
    ])
    progress_mat.set_stage(0)

    t_mat = time.time()
    material_map = _extract_material_from_ai_image(raw_path,
                                                     progress=progress_mat)
    progress_mat.finish()

    if material_map is not None:
        u.ok(f"材质图 {material_map.shape} "
             f"({time.time()-t_mat:.1f}s)")
    else:
        u.warn("材质反推失败，叠字用默认")

    # ══════════════════════════════════════════════════════════
    # [6] 文字叠字
    # ══════════════════════════════════════════════════════════
    rp = build_render_params(args)
    u.h(f"文字叠字 {ssaa}x")
    t1 = time.time()
    final = frame_render.render_fusion(
        raw_path, text, font,
        ssaa=ssaa, font_ratio=fr,
        seed=args.seed, render_params=rp,
        font_pos=font_pos, light=light,
        progress=prog.GlobalProgress(enabled=interactive),
        stage_offset=0,
        material_map=material_map)
    if not final:
        u.err("叠字失败")
        return 1
    t2 = time.time()
    u.ok(final.name)

    # ══════════════════════════════════════════════════════════
    # [7] 完成
    # ══════════════════════════════════════════════════════════
    u.h("完成")
    u.field("模式", "AI 生成")
    u.field("时间", local_time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    u.field("位置", f"{city} ({lat:.4f}, {lon:.4f})")
    u.field("天气", f"{weather.description} 云{weather.cloud}%")
    u.field("光源",
            f"{light.source} 方位{light.az:+.1f}° 高度{light.alt:+.1f}°")
    u.field("辐照度", f"{light.irradiance:.4f}")
    u.field("光照级别", str(light_lv))
    u.field("字体", font.name)
    u.field("输出", str(final))
    u.field("耗时", f"叠字 {t2 - t1:.1f}s")
    print()
    return 0


# ═══════════════════════════════════════════════════════════════════
def _mask(t):
    if not t or len(t) < 12:
        return "（未设置）"
    return f"{t[:8]}...{t[-4:]}"


def _resolve_output_size(args, defaults, interactive):
    u.h("输出尺寸")
    if args.resolution or args.aspect:
        res = args.resolution or defaults["resolution"]
        asp = args.aspect or defaults["aspect"]
        sz = config.SIZE_MAP.get((res, asp))
        if not sz:
            u.err(f"不支持 {res} {asp}")
            return None
        u.ok(f"{res} {asp} → {sz}")
        return sz, res, asp
    if not interactive:
        res, asp = defaults["resolution"], defaults["aspect"]
        sz = config.SIZE_MAP.get((res, asp)) or "2048x1152"
        return sz, res, asp
    if u.ask_yn("自定义尺寸？", "n"):
        mode = u.menu("模式", ["档位", "精确尺寸"], default=0)
        if mode == 0:
            res = config.SIZE_TIERS[
                u.menu("档位", config.SIZE_TIERS, default=1)]
            asp = config.ASPECT_RATIOS[
                u.menu("比例", config.ASPECT_RATIOS, default=3)]
            sz = config.SIZE_MAP.get((res, asp))
            if not sz:
                u.err("不支持")
                return None
        else:
            sz = u.ask("精确尺寸", "2048x1152")
            res, asp = sz, "custom"
        return sz, res, asp
    res, asp = defaults["resolution"], defaults["aspect"]
    sz = config.SIZE_MAP.get((res, asp)) or "2048x1152"
    return sz, res, asp