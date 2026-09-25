#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 离线模式编排

职责：
  内置底图 + 算法光照 + 叠字
  自定义图片 + 叠字（跳过光照）

光照 → 叠字严格分离：
  1. generate_lit_wall 只负责"生成带光照底图 lit.png"
  2. render_fusion 只负责"在 lit.png 上叠字"

本文件是编排层，可 import 跨框架（config + frame_light + frame_render）。
"""
import datetime
import time
from pathlib import Path

from PIL import Image

import config
import frame_light
import frame_render
from . import utils as u
from . import progress as prog


# ═══════════════════════════════════════════════════════════════════
# 交互式解析（供 offline + ai 共用，故为公开函数）
# ═══════════════════════════════════════════════════════════════════
def resolve_time(args, interactive):
    """时间解析：--time > 非交互 > 交互菜单。"""
    u.h("时间")
    if args.time:
        try:
            t = _parse_time(args.time)
            off = t.utcoffset()
            off_h = off.total_seconds() / 3600 if off else 0.0
            u.ok(f"输入 {args.time}")
            u.field("本地", t.strftime("%Y-%m-%d %H:%M:%S"))
            u.field("时区", str(t.tzinfo) or "（本地）")
            u.field("UTC 偏移", f"{off_h:+.1f}h")
            return t
        except ValueError as e:
            u.err(str(e))
            return None

    if not interactive:
        if args.no_ntp:
            t = datetime.datetime.now().astimezone()
            u.ok(f"系统时间 {t.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return t
        return _resolve_ntp(args, interactive=False)

    c = u.menu("时间来源",
               ["NTP 同步", "手动输入时间", "使用系统时间"], default=0)
    if c == 1:
        t = _manual_input_time()
        if t is None:
            t = datetime.datetime.now().astimezone()
        return t
    if c == 2:
        t = datetime.datetime.now().astimezone()
        u.ok(f"系统时间 {t.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        return t
    return _resolve_ntp(args, interactive=True)


def _parse_time(s):
    """本地时间解析（offline 专用）。"""
    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except ValueError:
        pass
    now = datetime.datetime.now()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%m-%d %H:%M", "%m-%d", "%H:%M"]:
        try:
            dt = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt: dt = dt.replace(year=now.year)
        if "%m" not in fmt: dt = dt.replace(month=now.month)
        if "%d" not in fmt: dt = dt.replace(day=now.day)
        return dt.astimezone()
    raise ValueError(f"无法解析时间: {s}")


def _manual_input_time(default_time=None):
    while True:
        default_str = (default_time.strftime("%Y-%m-%d %H:%M:%S")
                       if default_time else "2024-06-21 12:00")
        raw = u.ask("时间 (YYYY-MM-DD HH:MM[:SS] [±HH:MM])", default_str)
        if not raw:
            continue
        try:
            t = _parse_time(raw)
        except ValueError as e:
            u.err(f"格式错误: {e}")
            if not u.ask_yn("重试？", "y"):
                return None
            continue
        off = t.utcoffset()
        off_h = off.total_seconds() / 3600 if off else 0.0
        print()
        u.field("解析", t.strftime("%Y-%m-%d %H:%M:%S"))
        u.field("时区", str(t.tzinfo) or "（本地）")
        u.field("UTC 偏移", f"{off_h:+.1f}h")
        u.field("UTC", t.astimezone(datetime.timezone.utc)
                 .strftime("%Y-%m-%d %H:%M:%S"))
        if u.ask_yn("确认？", "y"):
            return t


def _resolve_ntp(args, interactive):
    import frame_light.astro as astro
    u.h("NTP 时间同步")

    host = args.ntp_host
    if host:
        u.info(f"指定 {host}")
        utc = astro.query_ntp(host)
        if utc:
            local = utc.astimezone()
            u.field("本地", local.strftime("%Y-%m-%d %H:%M:%S %Z"))
            if not interactive or u.ask_yn("采用？", "y"):
                return local

    if interactive:
        for host, desc in config.NTP_SERVERS:
            u.info(f"尝试 {host} ({desc})")
            utc = astro.query_ntp(host)
            if utc is None:
                u.warn("无响应")
                continue
            local = utc.astimezone()
            print()
            u.field("服务器", f"{host} ({desc})")
            u.field("本地", local.strftime("%Y-%m-%d %H:%M:%S %Z"))
            if u.ask_yn("采用？", "y"):
                return local
    else:
        for host, _ in config.NTP_SERVERS:
            utc = astro.query_ntp(host)
            if utc:
                local = utc.astimezone()
                u.ok(f"{host}: {local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                return local

    u.warn("NTP 不可用，使用系统时间")
    return datetime.datetime.now().astimezone()


def resolve_location(args, interactive):
    import frame_light.astro as astro
    u.h("位置解析")

    if args.lat is not None and args.lon is not None:
        u.ok(f"命令行 ({args.lat}, {args.lon})")
        return args.lat, args.lon, args.city or "Unknown", "cli"

    # 强制本机定位
    if getattr(args, "gps", False):
        got = astro.try_system_gps()
        if got:
            lat, lon, city, src = got
            u.field("本机定位", f"{src}  ({lat:.6f}, {lon:.6f}) {city}")
            if not interactive or u.ask_yn("采用？", "y"):
                return lat, lon, city, src
        else:
            u.warn("本机定位不可用（termux-api/系统权限/定位服务）")

    # 强制 IP 定位
    if getattr(args, "ip_loc", False):
        res = astro.try_ip_services()
        for r in res:
            u.field(r["name"], f"({r['lat']:.4f}, {r['lon']:.4f}) "
                              f"{r['country']} {r['region']} {r['city']}")
        if res:
            if not interactive:
                r = res[0]
                return (float(r["lat"]), float(r["lon"]),
                        r["city"] or "IP", r["name"])
            k = u.menu("IP 定位结果",
                       [f"{r['name']} ({r['lat']:.4f}, {r['lon']:.4f})"
                        for r in res], default=0)
            r = res[k]
            return float(r["lat"]), float(r["lon"]), r["city"], r["name"]
        u.warn("IP 定位不可用")

    if not args.no_gps:
        gps = astro.try_system_gps()
        if gps:
            lat, lon, city, src = gps
            u.field("本机定位", src)
            u.field("坐标", f"({lat:.6f}, {lon:.6f})")
            if not interactive or u.ask_yn("采用？", "y"):
                return lat, lon, city, src

    if not args.no_gps:
        services = config.GEO_SERVICES
        if args.geo_service:
            services = [s for s in config.GEO_SERVICES
                        if s[0] == args.geo_service] or config.GEO_SERVICES
        for svc in services:
            u.info(f"查询 {svc[0]}")
            result = astro.try_ip_service(svc)
            if result is None:
                continue
            lat, lon, city, region, country, name = result
            u.field("来源", f"IP ({name})")
            u.field("坐标", f"({lat:.6f}, {lon:.6f})")
            u.field("地区", f"{country} {region} {city}")
            if not interactive:
                return lat, lon, city or region, name
            if u.ask_yn("采用？", "y"):
                return lat, lon, city or region, name

    u.warn("手动输入")
    while True:
        try:
            lat = float(u.ask("纬度", "39.9042"))
            lon = float(u.ask("经度", "116.4074"))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                u.warn("超范围")
                continue
            return lat, lon, u.ask("城市", "Manual"), "manual"
        except ValueError:
            u.warn("格式错误")


def resolve_weather(args, lat, lon, interactive):
    import frame_light.astro as astro
    u.h("天气")

    d = {}
    try:
        d = config.get_defaults()
    except Exception:
        pass

    def _ov(cli_val, cfg_key):
        """命令行 > 设置默认 > None（用预设/实测）"""
        if cli_val is not None:
            return cli_val
        v = d.get(cfg_key)
        return v if v is not None else None

    override = args.weather or d.get("weather_override") or "auto"
    cloud = _ov(args.cloud, "cloud")
    precip = _ov(args.precip, "precip")
    vis = _ov(args.visibility, "visibility")
    hum = _ov(args.humidity, "humidity")

    if override and override != "auto":
        preset = config.WEATHER_PRESETS.get(
            override, config.WEATHER_PRESETS["clear"])
        w = astro.WeatherInfo(
            cloud=cloud if cloud is not None else preset["cloud"],
            vis=vis if vis is not None else preset["vis"],
            humidity=hum if hum is not None else preset.get("humidity", 40),
            precip=precip if precip is not None else preset["precip"],
            forced_type=override)
        u.ok(f"强制 {config.WEATHER_LABELS.get(override, override)}")
        u.field("云/水/视/湿",
                f"{w.cloud:.0f}% {w.precip:.1f}mm {w.vis:.0f}m "
                f"{w.humidity:.0f}%")
        return w, "override"

    if any(v is not None for v in (cloud, precip, vis, hum)):
        w = astro.WeatherInfo(
            cloud=cloud if cloud is not None else 0,
            vis=vis if vis is not None else 20000,
            humidity=hum if hum is not None else 40,
            precip=precip if precip is not None else 0.0)
        u.ok(f"手动 云{w.cloud}% 水{w.precip}mm 视{w.vis}m 湿{w.humidity}%")
        return w, "manual"

    u.info(f"查询 Open-Meteo ({lat:.4f}, {lon:.4f})")
    w = astro.fetch_weather(lat, lon)
    if w is None:
        u.warn("查询失败，使用晴天默认")
        return astro.WeatherInfo(), "default"
    print()
    u.field("天气", w.description)
    u.field("云量", f"{w.cloud}%")
    u.field("能见度", f"{w.vis/1000:.1f} km")
    u.field("湿度", f"{w.humidity}%")
    u.field("降水", f"{w.precip} mm")
    u.field("温度", f"{w.temp}°C")
    if not interactive:
        return w, "auto"
    if u.ask_yn("采用？", "y"):
        return w, "auto"
    return w, "manual"


def pick_text(args, interactive):
    u.h("文字内容")
    if args.text:
        text = args.text
    elif not interactive:
        text = "谎如昨日，嗤笑今朝"
    else:
        text = u.ask("文字", "谎如昨日，嗤笑今朝")
    if not text or not text.strip():
        text = "谎如昨日，嗤笑今朝"
        u.warn("空文字用默认")
    u.ok(text)
    return text


def pick_font_and_pos(args, defaults, interactive):
    u.h("字体选择")
    fonts = list_fonts()
    if not fonts:
        u.err("无字体")
        return None, None
    font = None
    if args.font:
        for f in fonts:
            if f.name == args.font or f.stem == args.font:
                font = f
                break
    if not font and defaults.get("font"):
        for f in fonts:
            if f.name == defaults["font"] or f.stem == defaults["font"]:
                font = f
                break
    if not font and interactive and len(fonts) > 1:
        idx = u.menu("可用字体", [f.stem for f in fonts], default=0)
        font = fonts[idx]
    if not font:
        import random
        font = random.choice(fonts)
    u.ok(font.name)

    u.h("字体位置")
    anchor = args.font_anchor or defaults["font_anchor"]
    pos_x = (args.font_pos_x if args.font_pos_x is not None
             else defaults["font_pos_x"])
    pos_y = (args.font_pos_y if args.font_pos_y is not None
             else defaults["font_pos_y"])
    if anchor not in config.ANCHORS:
        anchor = config.DEFAULT_ANCHOR
    pos_x = max(0.0, min(100.0, float(pos_x)))
    pos_y = max(0.0, min(100.0, float(pos_y)))
    u.field("锚点", anchor)
    u.field("位置", f"({pos_x:.0f}%, {pos_y:.0f}%)")
    return font, {"anchor": anchor, "x": pos_x, "y": pos_y}


def list_fonts():
    if not config.FONT_DIR.exists():
        return []
    fonts = []
    for ext in config.FONT_EXTENSIONS:
        fonts.extend(config.FONT_DIR.glob(f"*{ext}"))
    return sorted(fonts, key=lambda p: p.name.lower())


def list_bgs():
    if not config.BG_DIR.exists():
        return []
    files = []
    for ext in config.IMAGE_EXTENSIONS:
        files.extend(config.BG_DIR.glob(f"*{ext}"))
    return sorted(files, key=lambda p: p.name.lower())


def build_render_params(args):
    import numpy as np
    rp = {}
    if args.cinnabar:
        r, g, b = args.cinnabar
        rp["cinnabar"] = np.array([r, g, b], dtype=np.float32)
    if args.shadow_strength is not None:
        rp["shadow_strength"] = max(0.0, min(1.0, args.shadow_strength))
    aged = {}
    if args.noise_low is not None: aged["noise_low"] = args.noise_low
    if args.noise_mid is not None: aged["noise_mid"] = args.noise_mid
    if args.noise_high is not None: aged["noise_high"] = args.noise_high
    if args.diffusion is not None: aged["diffusion"] = args.diffusion
    if args.oxidation is not None: aged["oxidation"] = args.oxidation
    if aged:
        rp["aged"] = aged
    return rp


def confirm_render(pred, auto_yes=False):
    if auto_yes:
        return True
    u.h("结果预测")
    u.field("结论", pred["summary"])
    u.field("光斑预期", pred["patch_expected"])
    if pred["warnings"]:
        print()
        u.warn("以下情况需要注意：")
        for w in pred["warnings"]:
            print(f"    ! {w}")
        print()
        if pred["verdict"] == "warn":
            return u.ask_yn("仍要继续？", "y")
    else:
        u.ok("参数组合正常")
    return True


# ═══════════════════════════════════════════════════════════════════
# 模式 2：内置底图 + 光线追踪光照
# ═══════════════════════════════════════════════════════════════════
def run_bg_lit_generate(args, interactive=True) -> int:
    defaults = config.get_defaults()

    u.h("底图选择")
    bg_name = args.background or defaults.get("background") or None
    bgs = list_bgs()
    if not bgs:
        u.err(f"未在 {config.BG_DIR} 找到底图")
        return 1

    bg_path = None
    if bg_name:
        for b in bgs:
            if b.name == bg_name or b.stem == bg_name:
                bg_path = b
                break
        if not bg_path:
            u.warn(f"未找到 '{bg_name}'")
    if not bg_path and defaults.get("background"):
        for b in bgs:
            if (b.name == defaults["background"]
                    or b.stem == defaults["background"]):
                bg_path = b
                break
    if not bg_path and interactive and len(bgs) > 1:
        idx = u.menu("可用底图", [b.stem for b in bgs], default=0)
        bg_path = bgs[idx]
    if not bg_path:
        bg_path = bgs[0]

    with Image.open(bg_path) as im:
        W, H = im.size
    u.ok(f"{bg_path.name} ({W} x {H})")

    wall_img_check = Image.open(bg_path).convert("RGB")
    level, msg = frame_light.diagnose_wall(wall_img_check)
    if level == "too_dark":
        u.warn(msg)
    elif level in ("dark", "bright"):
        u.info(msg)

    local_time = resolve_time(args, interactive)
    if local_time is None:
        return 1

    _loc = resolve_location(args, interactive)
    if _loc is None:
        u.err("位置解析失败")
        return 1
    lat, lon, city, _ = _loc
    weather, _ = resolve_weather(args, lat, lon, interactive)

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
    u.field("色温", f"{[round(float(c), 2) for c in light.color]}")
    if light.irradiance > 0.0005:
        u.field("光斑中心",
                f"({light.patch_center_x:.2f}, {light.patch_center_y:.2f})")
        u.field("光斑大小",
                f"{light.patch_width:.2f} × {light.patch_height:.2f}")
    u.field("描述", light.description)
    if light.visibility_reason:
        u.field("可达性", light.visibility_reason)

    if light.source == "none":
        u.warn("当前无任何直射光（太阳/月亮均不可用）")
    elif light.is_night:
        u.info("当前为夜间场景（月光）")
    else:
        u.info("当前为日间场景（阳光）")

    u.h("窗户参数")
    win_scale = (args.window_scale if args.window_scale is not None
                 else defaults.get("window_scale", 0.65))
    grid_rows = (args.grid_rows if args.grid_rows is not None
                 else defaults.get("grid_rows", 3))
    grid_cols = (args.grid_cols if args.grid_cols is not None
                 else defaults.get("grid_cols", 2))
    grid_frame = (args.grid_frame if args.grid_frame is not None
                  else defaults.get("grid_frame_ratio", 0.18))

    u.field("窗户位置", win_side)
    u.field("光斑大小", win_scale)
    u.field("窗格", f"{grid_rows} x {grid_cols}")
    u.field("窗框缝隙", f"{grid_frame * 100:.0f}%")

    if args.dry_run:
        u.h("Dry Run")
        u.info("未生成")
        return 0

    pred = frame_light.predict_result(
        light, weather, wall_img=wall_img_check,
        grid_rows=grid_rows, grid_cols=grid_cols)
    if not confirm_render(pred, auto_yes=not interactive):
        u.warn("用户取消")
        return 0

    u.h("光线追踪光照")
    progress = prog.GlobalProgress(enabled=interactive)

    t0 = time.time()
    wall_img = Image.open(bg_path).convert("RGB")

    # 直接调用（不再传 scene_lights_fn）
    lit_img, meta = frame_render.generate_lit_wall(
        wall_img, light, weather,
        window_orientation=win_side,
        window_scale=win_scale,
        grid_rows=grid_rows, grid_cols=grid_cols,
        grid_frame_ratio=grid_frame,
        progress=progress)
    elapsed = time.time() - t0

    # Retinex 采样报告
    ret = meta.get("retinex", {})
    mat = meta.get("material_stats", {})
    if ret:
        u.h("光照数据")
        u.field("反射率均值", f"{ret.get('albedo_mean', 0):.3f}")
        u.field("反射率标准差", f"{ret.get('albedo_std', 0):.3f}")
        u.field("原图光照均值", f"{ret.get('S_mean', 0):.3f}")
        u.field("工作尺寸", ret.get("work_size", "?"))
        u.field("材质均值", f"{mat.get('albedo_mean', 1):.3f}")
        u.field("材质范围", f"[{mat.get('albedo_min', 1):.2f}, "
                            f"{mat.get('albedo_max', 1):.2f}]")
        u.field("粗糙度均值", f"{mat.get('roughness_mean', 0):.3f}")
        u.field("水面比例", f"{mat.get('water_ratio', 0)*100:.2f}%")
        u.field("I_traced max", f"{meta.get('I_traced_max', 0):.4f}")
        u.field("I_out max", f"{meta.get('I_out_max', 0):.4f}")
        u.field("太阳分波长",
                f"{[round(x, 3) for x in meta.get('sun_color_rgb', [])]}")
        u.info("光线追踪完成，反射率层已从原图恢复")

    out_dir = Path(args.output) if args.output else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = local_time.strftime("%Y%m%d_%H%M%S")
    prefix = args.output_name or "LIT"
    lit_path = out_dir / f"{prefix}_{stamp}_lit.png"
    lit_img.save(lit_path)
    u.ok(f"{lit_path.name} ({elapsed * 1000:.0f}ms)")

    if args.no_render:
        u.h("跳过文字叠字")
        u.info(f"光照底图已保存: {lit_path.name}")
        return 0

    # ══════════════════════════════════════════════════════════
    # 叠字（与光照完全独立）
    # ══════════════════════════════════════════════════════════
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

    # 叠字用 material_map（灰度）作为字体材质耦合
    material_map = meta.get("material_map", None)

    rp = build_render_params(args)
    u.h(f"文字叠字 {ssaa}x")
    t1 = time.time()
    final = frame_render.render_fusion(
        lit_path, text, font,
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

    keep_lit = args.keep_lit
    if not keep_lit and interactive:
        if u.ask_yn("保留中间光照底图？", "n"):
            keep_lit = True
    if not keep_lit:
        try:
            lit_path.unlink()
            u.info("已删除中间光照底图")
        except Exception:
            pass

    u.h("完成")
    u.field("模式", "内置底图 + 光线追踪光照")
    u.field("底图", bg_path.name)
    u.field("时间", local_time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    u.field("位置", f"{city} ({lat:.4f}, {lon:.4f})")
    u.field("天气", f"{weather.description} 云{weather.cloud}%")
    u.field("光源",
            f"{light.source} 方位{light.az:+.1f}° 高度{light.alt:+.1f}°")
    u.field("辐照度", f"{light.irradiance:.4f}")
    u.field("窗格", f"{grid_rows} x {grid_cols}")
    u.field("字体", font.name)
    u.field("成品", str(final))
    u.field("耗时", f"光照 {elapsed*1000:.0f}ms + 叠字 {t2-t1:.1f}s")
    print()
    return 0


# ═══════════════════════════════════════════════════════════════════
# 模式 3：自定义图片（跳过光照）
# ═══════════════════════════════════════════════════════════════════
def run_custom_image_generate(args, image_path: Path,
                               interactive=True) -> int:
    defaults = config.get_defaults()

    u.h("自定义图片")
    u.info("跳过光照计算，直接叠字")

    if not image_path.exists():
        u.err(f"图片不存在: {image_path}")
        return 1
    try:
        with Image.open(image_path) as im:
            W, H = im.size
    except Exception as e:
        u.err(f"无法读取: {e}")
        return 1
    u.ok(f"{image_path.name} ({W} x {H})")

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
        u.info("未生成")
        return 0

    out_dir = Path(args.output) if args.output else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.output_name or "CUSTOM"
    raw_path = out_dir / f"{prefix}_{stamp}_raw.png"
    try:
        Image.open(image_path).convert("RGB").save(raw_path)
    except Exception as e:
        u.err(f"处理失败: {e}")
        return 1

    if args.no_render:
        u.h("跳过文字叠字")
        u.info(f"底图副本已保存: {raw_path.name}")
        return 0

    rp = build_render_params(args)
    u.h(f"文字叠字 {ssaa}x")
    t1 = time.time()
    final = frame_render.render_fusion(
        raw_path, text, font,
        ssaa=ssaa, font_ratio=fr,
        seed=args.seed, render_params=rp,
        font_pos=font_pos, light=None,
        progress=prog.GlobalProgress(enabled=interactive),
        stage_offset=0)
    if not final:
        u.err("叠字失败")
        return 1
    t2 = time.time()
    u.ok(final.name)

    u.h("完成")
    u.field("模式", "自定义图片")
    u.field("原图", f"{image_path.name} ({W} x {H})")
    u.field("字体", font.name)
    u.field("输出", str(final))
    u.field("耗时", f"{t2 - t1:.1f}s")
    print()
    return 0