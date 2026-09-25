#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 设置中心（重建版）

分组：
  0 渲染与输出       （defaults 中的渲染/文字/窗户字段）
  1 光照与 3D 场景   （FACTORY_LIGHTING 全字段，含 scene 子组）
  2 天气默认         （预设 + 手动覆盖）
  3 文字与年代感     （朱红/噪声/扩散/氧化/阴影/材质耦合）
  4 AI 提示词        （FACTORY_PROMPTS 全字段）
  5 凭据             （Token / NTP / 定位服务）
  6 日志
  7 恢复出厂

设计：能改的一律可改（edit_mapping 自动适配类型），不藏参数。
本文件只 import config + tui。
"""
import json
from pathlib import Path

import config
from . import tui as T

# 渲染页里交给 edit_mapping 的字段（顺序即展示顺序）
RENDER_KEYS = [
    "resolution", "aspect", "ssaa",
    "font_ratio", "font", "font_anchor", "font_pos_x", "font_pos_y",
    "background", "keep_lit",
    "window_orientation", "window_scale",
    "grid_rows", "grid_cols", "grid_frame_ratio", "shadow_length",
    "smart_wrap",
    "visual_exposure", "visual_saturation", "material_coupling",
]
RENDER_LABELS = {
    "resolution": "分辨率档位", "aspect": "画面比例", "ssaa": "超采样倍数",
    "font_ratio": "字号比例", "font": "字体文件名",
    "font_anchor": "锚点", "font_pos_x": "位置 X%", "font_pos_y": "位置 Y%",
    "background": "默认底图", "keep_lit": "保留 lit.png",
    "window_orientation": "窗户朝向", "window_scale": "窗户大小",
    "grid_rows": "窗格行", "grid_cols": "窗格列",
    "grid_frame_ratio": "窗框占比", "shadow_length": "阴影倍率",
    "smart_wrap": "智能断行",
    "visual_exposure": "曝光", "visual_saturation": "饱和度",
    "material_coupling": "材质耦合强度",
}

LIGHT_LABELS = {
    "scene": "3D 场景",
    "room_w_m": "房间宽 m", "room_h_m": "房间高 m", "room_d_m": "房间深 m",
    "window_side": "窗在墙侧", "window_w_m": "窗户宽 m", "window_h_m": "窗户高 m",
    "window_cy_m": "窗户中心 Y", "window_cz_m": "窗户中心 Z",
    "grid_rows": "窗格行", "grid_cols": "窗格列",
    "grid_frame_ratio": "窗框占比",
    "camera_pos_m": "相机位置", "camera_fov_deg": "视场角",
    "aces_gain": "ACES 增益",
    "ambient_target_sun_max": "天光目标(日/最大)",
    "ambient_target_sun_min": "天光目标(日/最小)",
    "ambient_target_twilight": "天光目标(暮光)",
    "ambient_target_moon": "天光目标(月)",
    "ambient_target_none": "天光目标(无)",
    "ambient_cloud_threshold": "云量阈值",
    "vignette_strength": "渐晕强度",
    "material_strength": "材质强度",
    "aged_enabled": "启用年代感", "aged_noise": "年代感噪声",
    "aged_erode": "年代感侵蚀", "aged_dark_spots": "暗斑",
    "sensor_curve_strength": "CMOS 曲线",
    "shadow_blue_tint": "阴影冷色偏移",
    "wall_bump_strength": "墙面凹凸",
}

LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]


def _mask(t):
    if not t:
        return "（未设置）"
    return f"{t[:8]}…{t[-4:]}" if len(t) >= 12 else "（过短）"


def _save_defaults(d):
    config.save_settings(d)


def _save_lighting(d):
    config.save_lighting(d)


def _save_prompts(d):
    config.save_prompts(d)


# ═══════════════════════════════════════════════════════════════════
# 设置中心
# ═══════════════════════════════════════════════════════════════════
def settings_root():
    while True:
        d = config.get_defaults()
        tk = config.get_token()
        T.title("设置中心")
        T.panel("当前概览", [
            ("分辨率/比例", f"{d.get('resolution')} {d.get('aspect')}"),
            ("默认底图", d.get("background") or "（自动）"),
            ("字体/比例", f"{d.get('font') or '（默认）'} "
                       f"{d.get('font_ratio')}"),
            ("窗户", f"{d.get('window_orientation')} "
                   f"{d.get('grid_rows')}x{d.get('grid_cols')}"),
            ("天气默认", d.get("weather_override", "auto")),
            ("材质耦合", d.get("material_coupling", 0.0)),
            ("曝光/饱和", f"{d.get('visual_exposure')} / "
                       f"{d.get('visual_saturation')}"),
            ("Token", _mask(tk.get("api_token", ""))),
            ("日志", f"{d.get('log_level')} "
                   f"{'→文件' if d.get('log_to_file') else ''}"),
        ])
        c = T.menu("设置分组", [
            "渲染与输出",
            "光照与 3D 场景",
            "天气默认",
            "文字与年代感",
            "AI 提示词",
            "凭据（Token / NTP / 定位）",
            "日志",
            "恢复出厂",
        ], back="back")
        if c == "back":
            return 0
        if c == 0:
            _page_render()
        elif c == 1:
            T.edit_mapping("光照与 3D 场景", config.get_lighting(),
                           _save_lighting, label_map=LIGHT_LABELS,
                           note="数值均为物理/视觉系数，改动会立即影响下次渲染")
        elif c == 2:
            _page_weather()
        elif c == 3:
            _page_text()
        elif c == 4:
            T.edit_mapping("AI 提示词", config.get_prompts(), _save_prompts,
                           note="wall / vision / scene_profiles 等，供在线模式拼提示词")
        elif c == 5:
            _page_credentials()
        elif c == 6:
            _page_logging()
        else:
            _page_factory()


def _page_render():
    d = config.get_defaults()
    sub = {k: d.get(k, config.FACTORY_SETTINGS.get(k)) for k in RENDER_KEYS
           if (k in d or k in config.FACTORY_SETTINGS)}
    T.edit_mapping("渲染与输出", sub,
                   lambda s: _save_defaults({**config.get_defaults(), **s}),
                   label_map=RENDER_LABELS,
                   note="这些是「默认值」；生成向导里仍可临时覆盖")


def _page_weather():
    from .wizard import WEATHER_UI
    while True:
        d = config.get_defaults()
        cur = d.get("weather_override", "auto")
        idx = 0
        for i, (k, _, _) in enumerate(WEATHER_UI):
            if k == cur:
                idx = i
        T.title("天气默认")
        T.panel("当前", [
            ("预设", cur),
            ("云量覆盖", d.get("cloud") if d.get("cloud") is not None
             else "（用预设）"),
            ("降水覆盖", d.get("precip") if d.get("precip") is not None
             else "（用预设）"),
            ("能见度覆盖", d.get("visibility")
             if d.get("visibility") is not None else "（用预设）"),
            ("湿度覆盖", d.get("humidity") if d.get("humidity") is not None
             else "（用预设）"),
        ])
        c = T.menu("天气默认",
                   [f"预设：{lab}（{k}）" for k, lab, _ in WEATHER_UI]
                   + ["手动覆盖…", "清除全部覆盖"],
                   default=idx, back="back",
                   notes=[n for _, _, n in WEATHER_UI] + ["", ""])
        if c == "back":
            return
        if c < len(WEATHER_UI):
            d["weather_override"] = WEATHER_UI[c][0]
            _save_defaults(d)
            T.ok(f"默认天气 → {WEATHER_UI[c][1]}")
            continue
        if c == len(WEATHER_UI) + 1:
            for k in ("cloud", "precip", "visibility", "humidity"):
                d[k] = None
            _save_defaults(d)
            T.ok("已清除覆盖")
            continue
        T.section("手动覆盖（回车=保持；输入 none=清除该项）")

        def _ov(key, label, lo, hi, nd=0):
            cur_v = d.get(key)
            s = T.ask(label, "none" if cur_v is None else cur_v)
            if str(s).lower() in ("none", "auto", "预设"):
                d[key] = None
                return
            try:
                d[key] = round(max(lo, min(hi, float(s))), nd)
            except ValueError:
                T.warn("无效，保持")

        _ov("cloud", "云量 %（0~100）", 0, 100)
        _ov("precip", "降水 mm（0~50）", 0, 50, 1)
        _ov("visibility", "能见度 m（200~50000）", 200, 50000)
        _ov("humidity", "湿度 %（0~100）", 0, 100)
        _save_defaults(d)
        T.ok("已保存")


def _page_text():
    d = config.get_defaults()
    sub = {
        "cinnabar": [round(float(x), 4) for x in config.CINNABAR_REFLECTANCE],
        "noise_low": config.TEXT_NOISE_LOW_AMP,
        "noise_mid": config.TEXT_NOISE_MID_AMP,
        "noise_high": config.TEXT_NOISE_HIGH_AMP,
        "diffusion": config.DIFFUSION_AMP,
        "oxidation": config.OXIDATION_AMP,
        "shadow_strength": config.SHADOW_STRENGTH,
        "material_coupling": float(d.get("material_coupling", 0.0)),
        "smart_wrap": bool(d.get("smart_wrap", True)),
    }
    labels = {
        "cinnabar": "朱红反射率 RGB", "noise_low": "低频斑驳",
        "noise_mid": "中频斑驳", "noise_high": "高频毛糙",
        "diffusion": "颜料扩散", "oxidation": "氧化强度",
        "shadow_strength": "接触阴影强度", "material_coupling": "材质耦合强度",
        "smart_wrap": "智能断行（按标点）",
    }
    T.info("材质耦合会即时生效；朱红/噪声等常量若要长期生效请同时改 config.py")
    T.edit_mapping("文字与年代感", sub,
                   lambda s: _save_defaults({**config.get_defaults(), **s}),
                   label_map=labels)
    config.TEXT_MATERIAL_COUPLING = float(sub["material_coupling"])


def _page_location():
    """本机定位：查看缓存 / 抓取 / 手动写入 / 来源开关 / 清除。"""
    import frame_light.astro as astro
    while True:
        d = astro.load_device_location()
        provs, env = astro.available_providers()
        dfl = config.get_defaults()
        enabled = dfl.get("location_providers") or []
        T.title("本机定位")
        T.panel("环境", [
            ("运行环境", env),
            ("时区", astro.system_timezone() or "（未知）"),
            ("启用来源", "、".join(enabled) if enabled else "全部（按优先级）"),
            ("su 提权", dfl.get("location_use_su", False)),
        ])
        if d:
            lat, lon, city, src = d
            T.panel("缓存", [
                ("坐标", f"({lat:.6f}, {lon:.6f})"),
                ("城市", city),
                ("来源", src),
                ("时区", f"UTC{round(lon / 15):+g}"),
                ("文件", str(config.CONFIG_LOCATION)),
            ])
        else:
            T.warn("暂无本机定位缓存")
        c = T.menu("本机定位", [
            "重新获取（按 provider 链）",
            "手动写入坐标",
            "选择启用的定位来源",
            "切换 su 提权（Android）",
            "清除缓存",
        ], back="back")
        if c == "back":
            return
        if c == 0:
            got = astro.try_system_gps()
            if got:
                lat, lon, city, src = got
                astro.save_device_location(lat, lon, city, src)
                T.ok(f"已更新：{src} ({lat:.6f}, {lon:.6f}) {city}")
            else:
                T.warn("所有来源都失败")
                T.info("Android 可开系统定位服务/装 termux-api；"
                       "桌面可装 geoclue(gpsd)/modemmanager")
                T.info("也可用「手动写入坐标」或 --set-location")
        elif c == 1:
            lat = T.ask_float("纬度", -90, 90, 39.9042, 6)
            lon = T.ask_float("经度", -180, 180, 116.4074, 6)
            city = T.ask("城市名（可选）", "", allow_empty=True)
            if astro.save_device_location(lat, lon, city, "manual"):
                T.ok("已写入")
            else:
                T.err("写入失败")
        elif c == 2:
            _pick_providers(provs, enabled)
        elif c == 3:
            dfl["location_use_su"] = T.ask_bool("允许 su 提权执行 dumpsys",
                                                dfl.get("location_use_su", False))
            _save_defaults(dfl)
        else:
            try:
                config.CONFIG_LOCATION.unlink()
                T.ok("已清除")
            except FileNotFoundError:
                T.info("本来就没有")
            except Exception as e:
                T.err(f"失败: {e}")


def _pick_providers(provs, enabled):
    """勾选启用的定位来源（多选）。"""
    keys = [p["key"] for p in provs]
    cur = set(enabled) if enabled else set(keys)
    while True:
        T.section("启用的定位来源（回车=保存）")
        T.info("全部勾选 = 按默认优先级自动；全部取消 = 回到自动")
        opts = [f"{'[x]' if p['key'] in cur else '[ ]'} {p['key']:9s} "
                f"{p['label']}"
                + ("" if p["available"] else "   (当前不可用)")
                for p in provs]
        c = T.menu("来源", opts + ["（保存）"], default=len(opts))
        if c == len(opts):
            d = config.get_defaults()
            d["location_providers"] = [k for k in keys if k in cur] \
                if len(cur) != len(keys) else []
            _save_defaults(d)
            T.ok("已保存：" + ("（自动）" if not d["location_providers"]
                              else "、".join(d["location_providers"])))
            return
        k = keys[c]
        cur.discard(k) if k in cur else cur.add(k)


def _page_credentials():
    while True:
        tk = config.get_token()
        d = config.get_defaults()
        T.title("凭据")
        T.panel("当前", [
            ("API Token", _mask(tk.get("api_token", ""))),
            ("NTP 主机", d.get("ntp_host") or "（自动）"),
            ("定位服务", d.get("geo_service") or "（自动）"),
        ])
        c = T.menu("凭据", [
            "设置 / 更换 API Token",
            "测试 API Token",
            "设置 NTP 主机",
            "设置定位服务",
            "本机定位（查看 / 设置 / 清除）",
        ], back="back")
        if c == "back":
            return
        if c == 4:
            _page_location()
            continue
        if c == 0:
            s = T.ask("API Token（sk-…）",
                      tk.get("api_token") or "")
            tk["api_token"] = s.strip()
            config.save_token(tk)
            T.ok("已保存（文件权限 600）")
            _test_token()
        elif c == 1:
            _test_token()
        elif c == 2:
            d["ntp_host"] = T.ask("NTP 主机（空=自动轮询）",
                                  d.get("ntp_host") or "", allow_empty=True)
            _save_defaults(d)
            T.info("可选: " + ", ".join(h for h, _ in config.NTP_SERVERS))
        elif c == 3:
            d["geo_service"] = T.ask("定位服务（空=自动轮询）",
                                     d.get("geo_service") or "",
                                     allow_empty=True)
            _save_defaults(d)
            T.info("可选: " + ", ".join(s[0] for s in config.GEO_SERVICES))


def _test_token():
    tok = config.resolve_token()
    if not tok:
        T.err("未设置 Token")
        return
    try:
        import requests
        r = requests.get("https://apihub.agnes-ai.com/v1/models",
                         headers={"Authorization": "Bearer " + tok},
                         timeout=15)
        if r.status_code == 200:
            T.ok("Token 可用")
        else:
            T.warn(f"HTTP {r.status_code}（{r.text[:60]}）")
    except Exception as e:
        T.warn(f"测试失败: {e}")


def _page_logging():
    d = config.get_defaults()
    T.title("日志")
    cur = d.get("log_level", "INFO")
    idx = LOG_LEVELS.index(cur) if cur in LOG_LEVELS else 1
    d["log_level"] = LOG_LEVELS[T.menu("日志级别", LOG_LEVELS, default=idx)]
    d["log_to_file"] = T.ask_bool("同时写入文件", d.get("log_to_file", False))
    _save_defaults(d)
    T.ok(f"级别 {d['log_level']}  文件 {d['log_to_file']}")
    T.info(f"日志目录: {config.LOG_DIR}")


def _page_factory():
    T.title("恢复出厂")
    T.warn("会重置：渲染设置 / 光照 / 提示词（底图与字体不动）")
    if not T.ask_bool("确认重置", False):
        T.info("已取消")
        return
    try:
        config.ensure_config_files(force=True)
        T.ok("已恢复出厂")
    except Exception as e:
        T.err(f"失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 信息菜单
# ═══════════════════════════════════════════════════════════════════
def info_menu():
    while True:
        T.title("信息")
        c = T.menu("查看", [
            "字体列表", "底图列表", "分辨率档位",
            "NTP 服务器", "定位服务", "定位测试（本机 GPS / IP）",
            "当前配置", "环境自检",
        ], back="back")
        if c == "back":
            return
        if c == 0:
            cmd_list_fonts()
        elif c == 1:
            cmd_list_backgrounds()
        elif c == 2:
            cmd_list_sizes()
        elif c == 3:
            cmd_list_ntp()
        elif c == 4:
            cmd_list_services()
        elif c == 5:
            cmd_test_location()
        elif c == 6:
            cmd_show_config()
        else:
            self_check()
        T.pause()


def cmd_list_fonts():
    T.title("字体")
    fonts = []
    for ext in sorted(config.FONT_EXTENSIONS):
        fonts.extend(config.FONT_DIR.glob(f"*{ext}"))
    fonts = sorted(fonts, key=lambda p: p.name.lower())
    if not fonts:
        T.warn(f"{config.FONT_DIR} 下没有字体")
        return
    for i, f in enumerate(fonts):
        T.raw(f"[{i:02d}] {f.name}   {f.stat().st_size // 1024}KB")
    T.info(f"共 {len(fonts)} 个")


def cmd_list_backgrounds():
    from .offline import list_bgs
    T.title("底图")
    bgs = list_bgs()
    if not bgs:
        T.warn(f"{config.BG_DIR} 下没有底图")
        return
    from PIL import Image
    for i, b in enumerate(bgs):
        try:
            with Image.open(b) as im:
                wh = f"{im.size[0]}x{im.size[1]}"
        except Exception:
            wh = "?"
        T.raw(f"[{i:02d}] {b.name}   {wh}")
    T.info(f"共 {len(bgs)} 个，位于 {config.BG_DIR}")


def cmd_list_sizes():
    T.title("分辨率档位")
    for t in config.SIZE_TIERS:
        row = "  ".join(f"{a}={config.SIZE_MAP.get((t, a), '—')}"
                        for a in config.ASPECT_RATIOS)
        T.raw(f"{t}: {row}")


def cmd_list_ntp():
    T.title("NTP 服务器")
    for h, d in config.NTP_SERVERS:
        T.raw(f"{h}   {d}")
    T.info("可用 --ntp-host 指定，或在设置里固定")


def cmd_list_services():
    T.title("定位服务")
    for s in config.GEO_SERVICES:
        T.raw(f"{s[0]}   {s[1]}")
    T.info("可用 --geo-service 指定，或在设置里固定")


def cmd_test_location():
    """诊断定位链路：环境探测 + 各 provider 可用性 + 实际尝试 + IP 服务。"""
    import frame_light.astro as astro
    T.title("定位测试")

    T.section("运行环境")
    provs, env = astro.available_providers()
    T.raw(f"detect_env()   {env}")
    T.raw(f"时区           {astro.system_timezone() or '（未知）'}")
    tz_hit = astro._p_timezone()
    if tz_hit:
        T.raw(f"时区推算       ({tz_hit[0]:.2f}, {tz_hit[1]:.2f}) {tz_hit[2]}")

    T.section("定位来源（provider）")
    for p in provs:
        mark = T.green("✓") if p["available"] else T.grey("·")
        cur = T.cyan(" ←当前环境") if p["current"] else ""
        T.raw(f"{mark} {p['key']:9s} {p['label']}{cur}")

    T.section("实际尝试（按优先级）")
    got = astro.try_system_gps()
    if got:
        T.ok(f"命中：{got[3]}  ({got[0]:.6f}, {got[1]:.6f}) {got[2]}")
    else:
        T.warn("全部不可用（可手写缓存或开启定位服务）")

    T.section("本地缓存")
    d = astro.load_device_location()
    if d:
        T.ok(f"({d[0]:.6f}, {d[1]:.6f})  {d[2]}  来源 {d[3]}")
    else:
        T.info("无缓存（--set-location lat,lon[,city] 可写入）")

    T.section("IP 定位")
    res = astro.try_ip_services()
    if not res:
        T.warn("全部失败（检查网络）")
    for r in res:
        T.raw(f"{r['name']:22s} ({r['lat']:.4f}, {r['lon']:.4f})  "
              f"{r['country']} {r['region']} {r['city']}")


def cmd_show_config():
    T.title("当前配置")
    for name, path in (("settings", config.CONFIG_SETTINGS),
                       ("lighting", config.CONFIG_LIGHTING),
                       ("prompts", config.CONFIG_PROMPTS)):
        T.section(f"{name}  ({path})")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            T.raw(json.dumps(data, ensure_ascii=False, indent=2)[:1800])
        except Exception as e:
            T.warn(f"读取失败: {e}")
    T.section("token")
    T.raw(f"api_token = {_mask(config.get_token().get('api_token', ''))}")


def cmd_reset_config():
    _page_factory()


def self_check():
    """环境自检：依赖 / 目录 / 光照链路。"""
    T.title("环境自检")
    ok_all = True
    for mod in ("numpy", "PIL", "requests"):
        try:
            __import__(mod)
            T.ok(f"依赖 {mod}")
        except Exception as e:
            ok_all = False
            T.err(f"依赖 {mod}: {e}")
    for name, p in (("底图", config.BG_DIR), ("字体", config.FONT_DIR),
                    ("输出", config.OUTPUT_DIR), ("配置", config.CONFIG_DIR)):
        if Path(p).exists():
            T.ok(f"{name}目录 {p}")
        else:
            T.warn(f"{name}目录不存在: {p}")
    try:
        import datetime as _dt
        import frame_light
        w = frame_light.astro.WeatherInfo(cloud=0, vis=20000, humidity=40,
                                          precip=0.0, forced_type="clear")
        L = frame_light.compute_light(39.9, 116.4,
                                      _dt.datetime(2025, 6, 21, 4, 0), w)
        T.ok(f"光照链路 光源={L.source} 高度={L.alt:+.1f}° "
             f"辐照={L.irradiance:.3f} 天光={L.ambient_irradiance:.3f}")
    except Exception as e:
        ok_all = False
        T.err(f"光照链路失败: {e}")
    T.blank()
    if ok_all:
        T.ok("自检通过")
    else:
        T.warn("自检有项目未通过（见上）")