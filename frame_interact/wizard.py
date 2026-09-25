#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 参数向导（重建版）

把「一次生成」涉及的全部自由度集中到 Plan 里，按步骤分组：
  文字 / 字体 / 排版 / 底图 / 时间 / 位置 / 天气 / 光照与窗户 /
  渲染 / 物理参数 / 输出

设计要点：
  - 任意步骤可反复跳转修改（tui.Wizard）
  - 天气：预设 + 全手动（云量/降水/能见度/湿度）+ 实时效果预测
  - 字体：可选、可开关、可调大小/位置
  - 底图：列表选择 + 材质耦合开关（字形是否随材质起伏）
  - 结果可「回填到 args」，直接复用既有的非交互渲染链路

本文件可 import config + tui + frame_light（只读用）。
"""
import datetime

import config
from . import tui as T

# ═══════════════════════════════════════════════════════════════════
# 预设数据
# ═══════════════════════════════════════════════════════════════════
CITY_PRESETS = [
    ("北京", 39.9042, 116.4074),
    ("上海", 31.2304, 121.4737),
    ("广州", 23.1291, 113.2644),
    ("成都", 30.5728, 104.0668),
    ("西安", 34.3416, 108.9398),
    ("乌鲁木齐", 43.8256, 87.6168),
    ("哈尔滨", 45.8038, 126.5340),
    ("拉萨", 29.6520, 91.1721),
    ("东京", 35.6762, 139.6503),
    ("伦敦", 51.5074, -0.1278),
    ("纽约", 40.7128, -74.0060),
    ("悉尼", -33.8688, 151.2093),
]

WEATHER_UI = [
    ("auto", "自动", "按季节/气候推算云量"),
    ("clear", "晴", "云 0%，直射最强、光斑边界最锐"),
    ("cloudy", "多云", "云 45%，光斑变软"),
    ("overcast", "阴", "云 90%，几乎无直射、散射为主"),
    ("rain", "雨", "云 95%，叠加水痕"),
    ("snow", "雪", "云 90%，叠加雪花亮点"),
    ("haze", "雾霾", "能见度低，光斑明显模糊"),
]


# ═══════════════════════════════════════════════════════════════════
# Plan
# ═══════════════════════════════════════════════════════════════════
class Plan:
    """一次生成的全部可变参数。"""

    def __init__(self, defaults=None, d_light=None):
        d = defaults or {}
        self.mode = "bg"                     # bg / ai / custom

        # ── 文字 ──
        self.text = ""
        self.font = d.get("font", "") or ""
        self.font_ratio = float(d.get("font_ratio", 0.18))
        self.font_anchor = d.get("font_anchor", "center")
        self.font_pos_x = float(d.get("font_pos_x", 50.0))
        self.font_pos_y = float(d.get("font_pos_y", 50.0))
        self.ssaa = int(d.get("ssaa", 8))
        self.seed = None
        self.enable_text = True

        # ── 底图（离线）/ 提示词（在线）──
        self.background = d.get("background", "") or ""
        self.keep_lit = bool(d.get("keep_lit", False))
        self.resolution = d.get("resolution", "2K")
        self.aspect = d.get("aspect", "16:9")
        self.wall_desc = ""
        self.light_level = None

        # ── 时间 / 位置 ──
        self.time_mode = "now"               # now / manual / ntp
        self.local_dt = None                 # 本地钟表时间（naive）
        self.tz_offset = None                # 小时；None=按经度自动
        self.city = "北京"
        self.lat = 39.9042
        self.lon = 116.4074

        # ── 天气 ──
        self.weather_kind = d.get("weather_override", "auto") or "auto"
        self.cloud = None                    # None=用预设
        self.precip = None
        self.visibility = None
        self.humidity = None

        # ── 窗户 / 光照 ──
        self.window_orientation = d.get("window_orientation", "right")
        self.window_scale = float(d.get("window_scale", 0.65))
        self.grid_rows = int(d.get("grid_rows", 3))
        self.grid_cols = int(d.get("grid_cols", 2))
        self.grid_frame = float(d.get("grid_frame_ratio", 0.18))
        self.shadow_length = d.get("shadow_length", "auto")

        # ── 物理/年代感 ──
        self.cinnabar = list(config.CINNABAR_REFLECTANCE)
        self.noise_low = config.TEXT_NOISE_LOW_AMP
        self.noise_mid = config.TEXT_NOISE_MID_AMP
        self.noise_high = config.TEXT_NOISE_HIGH_AMP
        self.diffusion = config.DIFFUSION_AMP
        self.oxidation = config.OXIDATION_AMP
        self.shadow_strength = config.SHADOW_STRENGTH
        self.material_coupling = float(
            d.get("material_coupling", config.TEXT_MATERIAL_COUPLING))
        self.exposure = float(d.get("visual_exposure", 1.0))
        self.saturation = float(d.get("visual_saturation", 1.0))

        # ── 输出 ──
        self.output_dir = str(config.OUTPUT_DIR)
        self.output_name = ""

    # ── 派生 ──
    def tz(self):
        if self.tz_offset is not None:
            return self.tz_offset
        return round(self.lon / 15.0)

    def local_now(self):
        """该地「此刻」的本地钟表时间（以真实 UTC 为基准）。"""
        utc = datetime.datetime.now(datetime.timezone.utc).replace(
            tzinfo=None, microsecond=0)
        return utc + datetime.timedelta(hours=self.tz())

    def utc_naive(self):
        """astro 需要的 UTC-naive 时刻。"""
        if self.local_dt is None:
            return datetime.datetime.now(datetime.timezone.utc).replace(
                tzinfo=None, microsecond=0)
        return (self.local_dt
                - datetime.timedelta(hours=self.tz())).replace(microsecond=0)

    def time_str(self):
        """给 --time 用的带偏移 ISO 串（无歧义）。"""
        off = self.tz()
        sign = "+" if off >= 0 else "-"
        base = self.local_dt or self.local_now()
        return (base.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
                + f"{sign}{abs(int(off)):02d}:{abs(int(round((off % 1) * 60))):02d}")

    def clock_text(self):
        """当前设定时间的可读描述。"""
        if self.time_mode == "ntp":
            return "NTP 校时"
        t = self.local_dt or self.local_now()
        tag = "此刻" if self.local_dt is None else "指定"
        return f"{tag} {t:%m-%d %H:%M} (UTC{self.tz():+g})"

    def weather_info(self):
        import frame_light.astro as astro
        preset = config.WEATHER_PRESETS.get(self.weather_kind,
                                            config.WEATHER_PRESETS["clear"])
        return astro.WeatherInfo(
            cloud=self.cloud if self.cloud is not None else preset["cloud"],
            vis=self.visibility if self.visibility is not None else preset["vis"],
            humidity=(self.humidity if self.humidity is not None
                      else preset.get("humidity", 40)),
            precip=self.precip if self.precip is not None else preset["precip"],
            forced_type=self.weather_kind)

    def apply_runtime(self):
        """写回运行时全局（材质耦合 / 曝光 / 饱和度），不改设置文件。"""
        config.TEXT_MATERIAL_COUPLING = float(self.material_coupling)
        config.VISUAL_EXPOSURE = float(self.exposure)
        config.VISUAL_SATURATION = float(self.saturation)

    def apply_args(self, args):
        """回填 argparse 命名空间，复用非交互链路。"""
        args.text = self.text
        args.font = self.font or None
        args.font_ratio = self.font_ratio
        args.font_anchor = self.font_anchor
        args.font_pos_x = self.font_pos_x
        args.font_pos_y = self.font_pos_y
        args.ssaa = self.ssaa
        args.seed = self.seed
        args.background = self.background or None
        args.keep_lit = self.keep_lit
        args.resolution = self.resolution
        args.aspect = self.aspect
        args.wall_desc = self.wall_desc or None
        args.light_level = self.light_level
        args.time = self.time_str()
        args.lat = self.lat
        args.lon = self.lon
        args.city = self.city
        args.weather = self.weather_kind
        args.cloud = self.cloud
        args.precip = self.precip
        args.visibility = self.visibility
        args.humidity = self.humidity
        args.window_orientation = self.window_orientation
        args.window_scale = self.window_scale
        args.grid_rows = self.grid_rows
        args.grid_cols = self.grid_cols
        args.grid_frame = self.grid_frame
        args.shadow_length = self.shadow_length
        args.cinnabar = list(self.cinnabar)
        args.noise_low = self.noise_low
        args.noise_mid = self.noise_mid
        args.noise_high = self.noise_high
        args.diffusion = self.diffusion
        args.oxidation = self.oxidation
        args.shadow_strength = self.shadow_strength
        args.output = self.output_dir or None
        args.output_name = self.output_name or None
        args.no_ntp = True          # 时间已在向导里定好
        args.no_gps = True          # 位置已在向导里定好
        return args


# ═══════════════════════════════════════════════════════════════════
# 各步骤
# ═══════════════════════════════════════════════════════════════════
def _edit_text(P):
    T.section("文字内容")
    P.enable_text = T.ask_bool("叠加文字", P.enable_text)
    if not P.enable_text:
        P.text = ""
        T.info("已关闭叠字（只出光照底图）")
        return
    T.info("支持多行输入；半角逗号会自动分行，行尾保留「，」")
    T.info("例：谎如昨日，嗤笑今朝  →  两行")
    P.text = T.ask_text_block("文字", P.text)


def _list_fonts():
    if not config.FONT_DIR.exists():
        return []
    out = []
    for ext in sorted(config.FONT_EXTENSIONS):
        out.extend(sorted(config.FONT_DIR.glob(f"*{ext}")))
    return sorted(out, key=lambda p: p.name.lower())


def _edit_font(P):
    fonts = _list_fonts()
    if not fonts:
        T.warn(f"未找到字体（{config.FONT_DIR}），将使用内置默认")
        return
    names = [f.name for f in fonts]
    cur = 0
    if P.font:
        for i, n in enumerate(names):
            if n == P.font or n == P.font.rsplit(".", 1)[0]:
                cur = i
                break
    notes = ["当前" if i == cur else "" for i in range(len(names))]
    c = T.menu("选择字体", names, default=cur, notes=notes)
    P.font = fonts[c].name
    T.ok(f"字体 → {P.font}")


def _edit_layout(P):
    P.font_ratio = T.ask_float("字号比例（占画面高度）", 0.02, 0.60,
                               P.font_ratio, 3)
    anchors = config.ANCHORS
    try:
        d = anchors.index(P.font_anchor)
    except ValueError:
        d = 0
    an = T.menu("锚点", anchors, default=d)
    P.font_anchor = anchors[an]
    if P.font_anchor == "center":
        P.font_pos_x = T.ask_float("水平位置 %", 0, 100, P.font_pos_x, 1)
        P.font_pos_y = T.ask_float("垂直位置 %", 0, 100, P.font_pos_y, 1)
    else:
        P.font_pos_x = T.ask_float("锚点 X %", 0, 100, P.font_pos_x, 1)
        P.font_pos_y = T.ask_float("锚点 Y %", 0, 100, P.font_pos_y, 1)
    P.ssaa = T.ask_int("超采样倍数 SSAA（8 已足够，16 更慢）", 1, 16, P.ssaa)


def _edit_background(P):
    import frame_light  # noqa: F401
    bgs = []
    if config.BG_DIR.exists():
        for ext in config.IMAGE_EXTENSIONS:
            bgs.extend(sorted(config.BG_DIR.glob(f"*{ext}")))
        bgs = sorted(bgs, key=lambda p: p.name.lower())
    if not bgs:
        T.err(f"{config.BG_DIR} 下没有底图")
        return
    names = [b.name for b in bgs]
    cur = 0
    if P.background:
        for i, n in enumerate(names):
            if n == P.background or n.rsplit(".", 1)[0] == P.background:
                cur = i
                break
    c = T.menu("选择底图材质", names, default=cur)
    P.background = bgs[c].name
    T.ok(f"底图 → {P.background}")


def _edit_ai_asset(P):
    T.section("AI 底图（在线生成）")
    tiers = config.SIZE_TIERS
    d = tiers.index(P.resolution) if P.resolution in tiers else 1
    P.resolution = tiers[T.menu("分辨率档位", tiers, default=d,
                                notes=["快", "", "", "4K 限速，慎用"])]
    P.aspect = config.ASPECT_RATIOS[
        T.menu("画面比例", config.ASPECT_RATIOS,
               default=config.ASPECT_RATIOS.index(P.aspect)
               if P.aspect in config.ASPECT_RATIOS else 3)]
    T.info("墙材质描述（留空则用设置里的默认提示词）")
    P.wall_desc = T.ask("墙材质描述", P.wall_desc or "(默认)")
    if P.wall_desc in ("(默认)", ""):
        P.wall_desc = ""


def _edit_time(P):
    names = ["使用当前时间", "手动输入日期时间", "NTP 网络校时"]
    c = T.menu("时间", names, default=0)
    if c == 2:
        P.time_mode = "ntp"
        return
    if c == 0:
        P.time_mode = "now"
        return
    P.time_mode = "manual"
    now = datetime.datetime.now()
    while True:
        s = T.ask("日期时间 YYYY-MM-DD HH:MM",
                  P.local_dt.strftime("%Y-%m-%d %H:%M")
                  if P.local_dt else now.strftime("%Y-%m-%d %H:%M"))
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
                    "%Y/%m/%d %H:%M", "%m-%d %H:%M"):
            try:
                t = datetime.datetime.strptime(s, fmt)
                if "%Y" not in fmt:
                    t = t.replace(year=now.year)
                P.local_dt = t
                break
            except ValueError:
                continue
        else:
            T.warn("格式错误，例：2025-06-21 12:00")
            continue
        break
    auto = round(P.lon / 15.0)
    P.tz_offset = T.ask_float("该地时区偏移（小时，正=东）", -12, 14,
                              auto, 2)
    T.ok(f"本地 {P.local_dt:%Y-%m-%d %H:%M}  →  UTC "
         f"{P.utc_naive():%Y-%m-%d %H:%M}")


def _edit_location(P):
    import frame_light.astro as astro
    env = astro.detect_env()
    provs, _ = astro.available_providers()
    usable = [p["key"] for p in provs if p["available"]]
    n = len(CITY_PRESETS)
    names = ([f"{c[0]}  ({c[1]:.2f}, {c[2]:.2f})" for c in CITY_PRESETS]
             + ["本机 GPS 定位", "IP 定位（网络）", "手动输入经纬度",
                "把当前位置存为「本机定位」", "保持当前"])
    notes = ([""] * n
             + [f"环境={env}；可用来源: {'/'.join(usable) or '无'}",
                "逐个查询 IP 地理服务并可选",
                "直接填经纬度", "供下次一键使用", ""])
    c = T.menu("位置", names, default=n, notes=notes)

    if c == n + 4:
        return
    if c < n:
        P.city, P.lat, P.lon = CITY_PRESETS[c]
    elif c == n:
        _loc_from_device(P, astro)
        return
    elif c == n + 1:
        _loc_from_ip(P, astro)
        return
    elif c == n + 2:
        P.lat = T.ask_float("纬度", -90, 90, P.lat, 6)
        P.lon = T.ask_float("经度", -180, 180, P.lon, 6)
        P.city = T.ask("城市名", P.city)
    else:
        if astro.save_device_location(P.lat, P.lon, P.city, "manual"):
            T.ok(f"已存为本机定位：{P.city} ({P.lat:.4f}, {P.lon:.4f})")
        else:
            T.err("写入失败")
        return
    T.ok(f"{P.city}  ({P.lat:.4f}, {P.lon:.4f}, 时区 UTC{P.tz():+g})")


def _loc_from_device(P, astro):
    """本机 GPS：跨环境 provider 链（Termux/Android/GeoClue/gpsd/Modem/macOS/Windows/时区）。"""
    T.info("按 provider 链获取本机定位…")
    got = astro.try_system_gps()
    if not got:
        provs, env = astro.available_providers()
        T.warn(f"本机定位不可用（环境={env}）")
        for p in provs:
            if not p["available"]:
                T.raw(f"· {p['key']:9s} {p['label']}（不可用）")
        T.info("Android：开系统定位 / 装 termux-api / 开 su 提权")
        T.info("Linux：装 geoclue-2.0（where-am-i）、gpsd、modemmanager")
        T.info("macOS：brew install CoreLocationCLI；Windows：需允许定位")
        T.info("也可「手动输入经纬度」后「存为本机定位」")
        return
    lat, lon, city, src = got
    T.panel("本机定位", [
        ("来源", src),
        ("坐标", f"({lat:.6f}, {lon:.6f})"),
        ("城市", city),
        ("时区", f"UTC{round(lon / 15):+g}"),
    ])
    if T.ask_bool("采用", True):
        P.lat, P.lon = lat, lon
        P.city = city if city not in ("", "GPS", "?") else "本机定位"
        if T.ask_bool("同时存为默认本机定位", False):
            astro.save_device_location(lat, lon, P.city, src)
            T.ok("已写入缓存")
        T.ok(f"采用 {P.city} ({P.lat:.4f}, {P.lon:.4f})")


def _loc_from_ip(P, astro):
    """IP 定位：遍历服务并让用户挑一个。"""
    T.info("查询 IP 地理服务…")
    res = astro.try_ip_services()
    if not res:
        T.warn("所有 IP 定位服务均不可用（检查网络/代理）")
        return
    opts = [f"{r['name']}  ({r['lat']:.4f}, {r['lon']:.4f})"
            for r in res]
    notes = [f"{r['country']} {r['region']} {r['city']}" for r in res]
    k = T.menu("IP 定位结果", opts, default=0, notes=notes)
    r = res[k]
    P.lat, P.lon = float(r["lat"]), float(r["lon"])
    P.city = r["city"] if r["city"] not in ("", "?") else "IP定位"
    T.ok(f"{P.city} ({P.lat:.4f}, {P.lon:.4f})  来源 {r['name']}")


def weather_preview(P):
    """返回 (行列表, 提示)。用于天气步骤实时预览。"""
    import frame_light
    try:
        w = P.weather_info()
        lt = P.utc_naive() + datetime.timedelta(hours=P.tz())
        dt = datetime.datetime(2025, 6, 21, lt.hour, lt.minute)
        L = frame_light.compute_light(P.lat, P.lon, dt, w,
                                      window_orientation=P.window_orientation)
    except Exception as e:
        return [("预测", f"不可用: {e}")], None
    rows = [
        ("云量/降水", f"{w.cloud:.0f}%  {w.precip:.1f}mm  "
                      f"能见 {w.vis / 1000:.1f}km  湿度 {w.humidity:.0f}%"),
        ("主光源", f"{L.source}   高度 {L.alt:+.1f}°   方位 {L.az:+.1f}°"),
        ("辐照度", f"{L.irradiance:.4f}   天光 {L.ambient_irradiance:.4f}"),
    ]
    if L.visibility_reason:
        rows.append(("可达性", L.visibility_reason))
    return rows, None


def _edit_weather(P):
    while True:
        names = [f"{label}（{key}）" for key, label, _ in WEATHER_UI]
        names.append("手动微调（云量/降水/能见度/湿度）")
        notes = [d for _, _, d in WEATHER_UI] + ["完全放开"]
        cur = 0
        for i, (k, _, _) in enumerate(WEATHER_UI):
            if k == P.weather_kind:
                cur = i
        T.section("天气")
        T.info("预设决定直射强度与光斑软硬；手动可覆盖任何一项（None=用预设）")
        c = T.menu("天气", names, default=cur, notes=notes)
        if c < len(WEATHER_UI):
            P.weather_kind = WEATHER_UI[c][0]
            T.ok(f"预设 → {WEATHER_UI[c][1]}")
        else:
            T.section("手动微调")
            T.info("直接回车 = 保持当前值；输入 none = 回到用预设")
            def _opt(label, cur_v, lo, hi, nd=2):
                s = T.ask(label, "none" if cur_v is None else cur_v)
                if str(s).lower() in ("none", "预设", "auto"):
                    return None
                try:
                    v = float(s)
                except ValueError:
                    T.warn("无效，保持")
                    return cur_v
                return round(max(lo, min(hi, v)), nd)
            P.cloud = _opt("云量 %（0~100）", P.cloud, 0, 100, 0)
            P.precip = _opt("降水量 mm（0~50）", P.precip, 0, 50, 1)
            P.visibility = _opt("能见度 m（200~50000）", P.visibility,
                                200, 50000, 0)
            P.humidity = _opt("湿度 %（0~100）", P.humidity, 0, 100, 0)
            T.ok("已更新手动覆盖")
        rows, _ = weather_preview(P)
        T.panel("效果预测", rows, note="预测基于 6 月 21 日同一钟点，仅示意")
        if not T.ask_bool("继续调整天气", False):
            return


def _edit_window(P):
    T.section("窗户与光照几何")
    opts = list(config.WINDOW_ORIENTATIONS)
    d = opts.index(P.window_orientation) if P.window_orientation in opts else 0
    P.window_orientation = opts[T.menu(
        "窗户朝向（左=西向，右=东向）", opts, default=d,
        notes=["西向（下午光）", "东向（上午光）"])]
    P.window_scale = T.ask_float("窗户大小系数", 0.2, 1.2, P.window_scale, 2)
    P.grid_rows = T.ask_int("窗格行数", 1, 8, P.grid_rows)
    P.grid_cols = T.ask_int("窗格列数", 1, 8, P.grid_cols)
    P.grid_frame = T.ask_float("窗框占比", 0.02, 0.5, P.grid_frame, 3)
    s = T.ask("阴影长度倍率（auto 或 0.5~4.0）", str(P.shadow_length))
    if str(s).lower() == "auto":
        P.shadow_length = "auto"
    else:
        try:
            P.shadow_length = max(0.5, min(4.0, float(s)))
        except ValueError:
            P.shadow_length = "auto"


def _edit_render(P):
    T.section("渲染精度")
    P.ssaa = T.ask_int("超采样 SSAA", 1, 16, P.ssaa)
    s = T.ask("随机种子（留空=随机）", "" if P.seed is None else P.seed,
              allow_empty=True)
    P.seed = None if s == "" else int(float(s))
    P.keep_lit = T.ask_bool("保留中间光照底图 lit.png", P.keep_lit)


def _edit_physics(P):
    T.section("颜料 / 年代感 / 材质耦合")
    T.info("朱红反射率：叠字处对光的乘性反射（越大越亮）")
    P.cinnabar = T.ask_rgb("朱红反射率", P.cinnabar)
    P.noise_low = T.ask_float("低频斑驳", 0.0, 0.6, P.noise_low, 3)
    P.noise_mid = T.ask_float("中频斑驳", 0.0, 0.6, P.noise_mid, 3)
    P.noise_high = T.ask_float("高频毛糙", 0.0, 0.6, P.noise_high, 3)
    P.diffusion = T.ask_float("颜料扩散", 0.0, 0.8, P.diffusion, 3)
    P.oxidation = T.ask_float("氧化强度", 0.0, 0.8, P.oxidation, 3)
    P.shadow_strength = T.ask_float("接触阴影强度", 0.0, 1.0,
                                    P.shadow_strength, 3)
    T.section("材质耦合")
    T.info("开启后：字形透明度随墙面材质起伏变化（凸处更实、凹处更虚）")
    T.info("参考实现没有这一步，默认关闭；开启会让字更「吃进」墙里")
    P.material_coupling = 0.0 if not T.ask_bool(
        "启用材质耦合", P.material_coupling > 0) else T.ask_float(
        "耦合强度", 0.0, 1.0, P.material_coupling or 0.4, 3)


def _edit_visual(P):
    T.section("画面微调")
    P.exposure = T.ask_float("曝光", 0.2, 3.0, P.exposure, 3)
    P.saturation = T.ask_float("饱和度", 0.0, 3.0, P.saturation, 3)


def _edit_output(P):
    T.section("输出")
    P.output_dir = T.ask("输出目录", P.output_dir)
    P.output_name = T.ask("文件名前缀（留空=LIT/AI）", P.output_name,
                          allow_empty=True)


# ═══════════════════════════════════════════════════════════════════
# 组装
# ═══════════════════════════════════════════════════════════════════
def _sum(fn, fallback="—"):
    try:
        return fn()
    except Exception:
        return fallback


def build_steps(P):
    steps = []
    if P.enable_text or True:
        steps.append(T.Step(
            "text", "文字",
            lambda: _edit_text(P),
            lambda: (P.text.replace("\n", " / ") or "（无）")
            if P.enable_text else "已关闭"))
    steps.append(T.Step("font", "字体", lambda: _edit_font(P),
                        lambda: P.font or "默认"))
    steps.append(T.Step(
        "layout", "排版", lambda: _edit_layout(P),
        lambda: f"比例{P.font_ratio:g} {P.font_anchor} "
                f"({P.font_pos_x:g},{P.font_pos_y:g}) SSAA{P.ssaa}"))
    if P.mode == "bg":
        steps.append(T.Step("bg", "底图", lambda: _edit_background(P),
                            lambda: P.background or "（未选）"))
    if P.mode == "ai":
        steps.append(T.Step(
            "asset", "底图/AI", lambda: _edit_ai_asset(P),
            lambda: f"{P.resolution} {P.aspect} "
                    f"{'(默认墙)' if not P.wall_desc else '自定义墙'}"))
    steps.append(T.Step(
        "time", "时间", lambda: _edit_time(P),
        lambda: P.clock_text()))
    steps.append(T.Step(
        "loc", "位置", lambda: _edit_location(P),
        lambda: f"{P.city} ({P.lat:.2f},{P.lon:.2f})"))
    steps.append(T.Step(
        "weather", "天气", lambda: _edit_weather(P),
        lambda: f"{P.weather_kind}"
                + (f" 云{P.cloud:.0f}%" if P.cloud is not None else "")
                + (f" 雨{P.precip:.1f}" if P.precip is not None else "")))
    if P.mode in ("bg", "ai"):
        steps.append(T.Step(
            "window", "光照", lambda: _edit_window(P),
            lambda: f"{P.window_orientation} 窗格{P.grid_rows}x{P.grid_cols} "
                    f"阴影{P.shadow_length}"))
    steps.append(T.Step("render", "渲染", lambda: _edit_render(P),
                        lambda: f"SSAA{P.ssaa} seed={P.seed}"))
    steps.append(T.Step(
        "phys", "年代感", lambda: _edit_physics(P),
        lambda: f"耦合{P.material_coupling:g} 扩散{P.diffusion:g} "
                f"阴影{P.shadow_strength:g}"))
    steps.append(T.Step("visual", "画面", lambda: _edit_visual(P),
                        lambda: f"曝光{P.exposure:g} 饱和{P.saturation:g}"))
    steps.append(T.Step("out", "输出", lambda: _edit_output(P),
                        lambda: P.output_dir))
    return steps


def plan_from_args(args, mode, defaults=None):
    """用命令行参数预填 Plan（命令行优先，其余取设置默认）。"""
    P = Plan(defaults or config.get_defaults())
    P.mode = mode

    def _g(name):
        return getattr(args, name, None)

    if _g("text"):
        P.text = args.text
    if _g("font"):
        P.font = args.font
    for attr, field in (("font_ratio", "font_ratio"),
                        ("font_anchor", "font_anchor"),
                        ("font_pos_x", "font_pos_x"),
                        ("font_pos_y", "font_pos_y"),
                        ("ssaa", "ssaa"),
                        ("resolution", "resolution"),
                        ("aspect", "aspect"),
                        ("window_orientation", "window_orientation"),
                        ("window_scale", "window_scale"),
                        ("grid_rows", "grid_rows"),
                        ("grid_cols", "grid_cols"),
                        ("grid_frame", "grid_frame"),
                        ("shadow_length", "shadow_length"),
                        ("wall_desc", "wall_desc"),
                        ("city", "city")):
        v = _g(attr)
        if v is not None:
            setattr(P, field, v)
    if _g("background"):
        P.background = args.background
    if _g("keep_lit"):
        P.keep_lit = True
    if _g("lat") is not None:
        P.lat = args.lat
    if _g("lon") is not None:
        P.lon = args.lon
    if _g("seed") is not None:
        P.seed = args.seed
    if _g("light_level") is not None:
        P.light_level = args.light_level
    if _g("output"):
        P.output_dir = args.output
    if _g("output_name"):
        P.output_name = args.output_name

    # 天气
    if _g("weather"):
        P.weather_kind = args.weather
    for attr in ("cloud", "precip", "visibility", "humidity"):
        v = _g(attr)
        if v is not None:
            setattr(P, attr, v)

    # 物理
    if _g("cinnabar"):
        P.cinnabar = list(args.cinnabar)
    for attr, field in (("noise_low", "noise_low"),
                        ("noise_mid", "noise_mid"),
                        ("noise_high", "noise_high"),
                        ("diffusion", "diffusion"),
                        ("oxidation", "oxidation"),
                        ("shadow_strength", "shadow_strength"),
                        ("material_coupling", "material_coupling"),
                        ("exposure", "exposure"),
                        ("saturation", "saturation")):
        v = _g(attr)
        if v is not None:
            setattr(P, field, v)

    # 时间
    if _g("time"):
        P.time_mode = "manual"
        try:
            import datetime as _d
            P.local_dt = _d.datetime.fromisoformat(args.time)
            if P.local_dt.tzinfo is not None:
                off = P.local_dt.utcoffset()
                P.tz_offset = off.total_seconds() / 3600.0
                P.local_dt = P.local_dt.replace(tzinfo=None)
        except ValueError:
            P.time_mode = "now"
    return P


def run(P, title_text="参数向导") -> bool:
    """跑一遍向导；True=确认生成。"""
    steps = build_steps(P)
    wiz = T.Wizard(P, steps, title_text=title_text,
                   confirm_label="✓ 开始生成")
    return wiz.run()