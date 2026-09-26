#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数注册表（Single Source of Truth）—— 每个细分方面 ≥15 个参数。

规则（见 agent.md）
══════════════════════════════════════════════════════════════════════
· **物理量优先**：每个参数必须是可测量的物理量或可推导的几何量，带单位与范围。
· **风格手调 ≤5**：`kind="tunable"` 的全局项总数受自测守门限制；
  其余都是 `physical`（材料/天体/大气常数）或 `derived`（由别的量算出）。
· **每个方面 ≥15 个参数**：由 tests/test_params.py 强制。

字段：
    key      规范键名（点分层级：aspect.name）
    unit     单位（"-" = 无量纲）
    default  默认值（必须落在 [lo, hi]）
    lo, hi   物理/工程有效范围（不是"审美范围"）
    kind     physical | derived | tunable
    src      出处（常数/公式/标准）

这个注册表驱动三件事：
    1) 渲染器读默认值与范围（不再各处硬编码）
    2) `tools/gen_params_doc.py` 自动生成 `docs/参数总表.md`
    3) 自测守门：参数计数、范围、唯一性、tunable 限额
"""
from typing import Dict, List, NamedTuple, Optional


class P(NamedTuple):
    key: str
    unit: str
    default: float
    lo: float
    hi: float
    kind: str
    src: str


def _s(key, default, kind="derived", src="", lo=0.0, hi=1e9, unit="-"):
    """标量参数快捷构造。"""
    return P(key, unit, float(default), float(lo), float(hi), kind, src)


# ═══════════════════════════════════════════════════════════════════
# ① 太阳（15+）
# ═══════════════════════════════════════════════════════════════════
SUN: List[P] = [
    _s("sun.azimuth_deg", 180.0, "derived", "天文算法", 0, 360, "°"),
    _s("sun.altitude_deg", 45.0, "derived", "天文算法", -90, 90, "°"),
    _s("sun.angular_diameter_deg", 0.5334, "physical", "1AU 视直径", 0.52, 0.55, "°"),
    _s("sun.distance_au", 1.0, "derived", "轨道偏心率", 0.983, 1.017, "AU"),
    _s("sun.limb_darkening_u1", 0.85, "physical", "二次定律 a1", 0.0, 1.2, "-"),
    _s("sun.limb_darkening_u2", -0.15, "physical", "二次定律 a2", -0.5, 0.5, "-"),
    _s("sun.irradiance_w_m2", 1050.0, "derived", "AM1.5 参考", 0, 1400, "W/m²"),
    _s("sun.rayleigh_tau550", 0.098, "physical", "瑞利光学厚度", 0.08, 0.12, "-"),
    _s("sun.mie_tau550", 0.05, "physical", "气溶胶基线", 0.01, 0.6, "-"),
    _s("sun.ozone_column_du", 300.0, "physical", "TOMS 气候值", 220, 450, "DU"),
    _s("sun.water_vapor_cm", 1.5, "derived", "湿度/温度", 0.2, 6.0, "cm"),
    _s("sun.angstrom_exponent", 1.3, "physical", "气溶胶波长依赖", 0.5, 2.5, "-"),
    _s("sun.airmass", 1.41, "derived", "Kasten-Young", 1.0, 40.0, "-"),
    _s("sun.direct_fraction", 0.81, "derived", "直射/总量", 0.0, 1.0, "-"),
    _s("sun.spectral_rgb_weights_r", 0.95, "derived", "分波长透过率", 0.3, 1.0, "-"),
    _s("sun.spectral_rgb_weights_g", 0.90, "derived", "分波长透过率", 0.3, 1.0, "-"),
    _s("sun.spectral_rgb_weights_b", 0.78, "derived", "分波长透过率", 0.2, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ② 天空穹顶（15+）
# ═══════════════════════════════════════════════════════════════════
SKY: List[P] = [
    _s("sky.zenith_radiance", 0.082, "derived", "由漫射照度标定", 0.0, 1.0, "W/m²/sr"),
    _s("sky.shape_model", 1.0, "physical", "1=CIE阴天 2=晴天 3=霾", 1, 3, "-"),
    _s("sky.overcast_grad", 2.0, "physical", "CIE (1+2cosθ)/3 的 2", 1.0, 3.0, "-"),
    _s("sky.horizon_boost", 0.45, "physical", "晴天低空增亮", 0.0, 1.5, "-"),
    _s("sky.circumsolar_ratio", 0.15, "physical", "环日辐射占比", 0.0, 1.0, "-"),
    _s("sky.turbidity", 2.5, "physical", "Linke 浑浊度", 1.5, 8.0, "-"),
    _s("sky.diffuse_horizontal", 0.19, "derived", "天气模型输出", 0.0, 1.0, "-"),
    _s("sky.dome_n_az", 36.0, "tunable", "精度/速度折中", 8, 256, "-"),
    _s("sky.dome_n_el", 9.0, "tunable", "精度/速度折中", 4, 128, "-"),
    _s("sky.ground_reflectance", 0.25, "physical", "地面反照率回照", 0.0, 0.9, "-"),
    _s("sky.temperature_cct", 11000.0, "derived", "天光色温", 4000, 25000, "K"),
    _s("sky.stars_density", 0.0, "derived", "夜间星空密度", 0.0, 1.0, "-"),
    _s("sky.airglow", 0.008, "physical", "夜空背景辉光", 0.0, 0.05, "-"),
    _s("sky.horizon_band_deg", 6.0, "physical", "地平线亮带厚度", 0.0, 30.0, "°"),
    _s("sky.polarization", 0.0, "physical", "线性偏振度（可选）", 0.0, 0.8, "-"),
    _s("sky.zenith_angle_ref", 0.0, "derived", "参考天顶角", 0.0, 90.0, "°"),
]

# ═══════════════════════════════════════════════════════════════════
# ③ 云（15+）
# ═══════════════════════════════════════════════════════════════════
CLOUD: List[P] = [
    _s("cloud.cover_fraction", 0.85, "derived", "API/预设", 0.0, 1.0, "-"),
    _s("cloud.optical_depth", 3.0, "physical", "厚云 τ", 0.0, 60.0, "-"),
    _s("cloud.single_scatter_albedo", 0.90, "physical", "水滴 ω", 0.7, 1.0, "-"),
    _s("cloud.asymmetry_g", 0.85, "physical", "Henyey-Greenstein", 0.5, 0.95, "-"),
    _s("cloud.base_altitude_m", 800.0, "physical", "云底高", 100, 4000, "m"),
    _s("cloud.thickness_m", 400.0, "physical", "云层厚度", 50, 3000, "m"),
    _s("cloud.lwp_g_m2", 120.0, "derived", "液态水路径", 0, 2000, "g/m²"),
    _s("cloud.droplet_radius_um", 10.0, "physical", "有效半径", 3, 30, "μm"),
    _s("cloud.precip_rate_mm_h", 0.6, "derived", "降水率", 0.0, 60.0, "mm/h"),
    _s("cloud.burst_period_min", 26.0, "derived", "阵雨周期", 5.0, 120.0, "min"),
    _s("cloud.burst_depth", 0.55, "derived", "云开云合幅度", 0.0, 1.0, "-"),
    _s("cloud.edge_softness", 0.35, "physical", "云边缘过渡", 0.0, 1.0, "-"),
    _s("cloud.slab_count", 3.0, "physical", "分层数", 1, 8, "-"),
    _s("cloud.temporal_seed", 20260926.0, "physical", "确定性种子", 0, 1e9, "-"),
    _s("cloud.temperature_c", 15.0, "physical", "云中温度（雨/雪判据）", -40, 40, "°C"),
]

# ═══════════════════════════════════════════════════════════════════
# ④ 大气 / 气溶胶（15+）
# ═══════════════════════════════════════════════════════════════════
ATMOS: List[P] = [
    _s("atmos.aerosol_optical_depth", 0.15, "physical", "AOD550", 0.01, 3.0, "-"),
    _s("atmos.visibility_m", 20000.0, "derived", "API", 50.0, 50000.0, "m"),
    _s("atmos.koschmieder_k", 3.912, "physical", "能见度→散射系数", 3.912, 3.912, "-"),
    _s("atmos.pressure_hpa", 1013.25, "physical", "标准大气压", 500, 1100, "hPa"),
    _s("atmos.temperature_c", 20.0, "derived", "API", -60, 60, "°C"),
    _s("atmos.humidity_rel", 0.5, "derived", "API", 0.0, 1.0, "-"),
    _s("atmos.lapse_rate_k_km", 6.5, "physical", "温度垂直梯度", 4.0, 10.0, "K/km"),
    _s("atmos.ozone_absorption", 0.016, "physical", "Chappuis 带", 0.005, 0.05, "-"),
    _s("atmos.rayleigh_scale_height_m", 8000.0, "physical", "瑞利标高", 7000, 9000, "m"),
    _s("atmos.angstrom_beta", 0.15, "physical", "浑浊度系数", 0.01, 1.0, "-"),
    _s("atmos.refraction_coeff", 0.00028, "physical", "地平线折射压缩", 0.0, 0.001, "-"),
    _s("atmos.dispersion_abbe", 58.0, "physical", "折射色散（Abbe 数）", 20, 90, "-"),
    _s("atmos.mie_g", 0.7, "physical", "气溶胶不对称因子", 0.4, 0.95, "-"),
    _s("atmos.cloud_mod_factor", 0.25, "derived", "CMF(c)", 0.05, 1.0, "-"),
    _s("atmos.vis_transmittance", 1.0, "derived", "气溶胶透过率", 0.0, 1.0, "-"),
    _s("atmos.precipitable_water_cm", 1.5, "derived", "水汽柱", 0.1, 6.0, "cm"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑤ 降水 / 湿度 / 地面状态（15+）
# ═══════════════════════════════════════════════════════════════════
PRECIP: List[P] = [
    _s("precip.rate_mm_h", 0.0, "derived", "API/预设", 0.0, 60.0, "mm/h"),
    _s("precip.water_film", 0.0, "derived", "1-e^(-p/0.5)", 0.0, 1.0, "-"),
    _s("precip.film_ref_mm", 0.50, "tunable", "水膜饱和降水率", 0.05, 3.0, "mm/h"),
    _s("precip.snow_state", 0.0, "derived", "temp<2℃ 且 p>0", 0.0, 1.0, "-"),
    _s("precip.ground_state", 0.25, "derived", "雪0.8/干0.25/湿0.07", 0.05, 0.85, "-"),
    _s("precip.wet_specular_gain", 0.5, "derived", "水膜→镜面增强", 0.0, 1.0, "-"),
    _s("precip.wet_albedo_drop", 0.28, "derived", "水膜→压暗反照率", 0.0, 0.6, "-"),
    _s("precip.fog_droplet_um", 8.0, "physical", "雾滴半径", 1.0, 30.0, "μm"),
    _s("precip.rain_drop_um", 900.0, "physical", "雨滴半径", 100, 3000, "μm"),
    _s("precip.snow_flake_mm", 3.0, "physical", "雪花直径", 0.2, 15.0, "mm"),
    _s("precip.wind_speed_ms", 2.0, "derived", "API", 0.0, 40.0, "m/s"),
    _s("precip.wind_dir_deg", 0.0, "derived", "API", 0.0, 360.0, "°"),
    _s("precip.rain_streak_tilt", 0.0, "derived", "风偏斜", -1.0, 1.0, "-"),
    _s("precip.rainbow_probability", 0.0, "derived", "背向太阳+水汽", 0.0, 1.0, "-"),
    _s("precip.splash_fraction", 0.0, "derived", "溅射占比", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑥ 地理 / 时间（15+）
# ═══════════════════════════════════════════════════════════════════
GEO: List[P] = [
    _s("geo.latitude_deg", 39.9042, "physical", "用户输入", -90, 90, "°"),
    _s("geo.longitude_deg", 116.4074, "physical", "用户输入", -180, 180, "°"),
    _s("geo.altitude_m", 47.0, "physical", "用户输入", -400, 5000, "m"),
    _s("geo.timezone_offset_h", 8.0, "physical", "用户输入", -12, 14, "h"),
    _s("geo.dst_offset_h", 0.0, "physical", "夏令时", -1, 1, "h"),
    _s("geo.day_of_year", 269.0, "derived", "日期", 1, 366, "-"),
    _s("geo.solar_declination_deg", -1.0, "derived", "Cooper/Spencer", -23.44, 23.44, "°"),
    _s("geo.hour_angle_deg", 0.0, "derived", "地方恒星时", -180, 180, "°"),
    _s("geo.equation_of_time_min", 0.0, "derived", "均时差", -17, 17, "min"),
    _s("geo.angular_speed_deg_h", 15.0, "physical", "地球自转", 14.0, 16.0, "°/h"),
    _s("geo.day_length_h", 12.0, "derived", "日出日落", 0.0, 24.0, "h"),
    _s("geo.sunrise_az_deg", 90.0, "derived", "日出方位", 0, 360, "°"),
    _s("geo.sunset_az_deg", 270.0, "derived", "日落方位", 0, 360, "°"),
    _s("geo.twilight_alt_deg", 10.0, "physical", "视觉暗适应阈值", 0.0, 18.0, "°"),
    _s("geo.track_tilt_deg", 50.0, "derived", "日轨倾角（纬度决定）", 0.0, 90.0, "°"),
    _s("geo.curvature_km", 6371.0, "physical", "地球半径", 6371.0, 6371.0, "km"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑦ 房间几何（15+）
# ═══════════════════════════════════════════════════════════════════
ROOM: List[P] = [
    _s("room.width_m", 4.0, "physical", "测量", 1.0, 30.0, "m"),
    _s("room.height_m", 3.0, "physical", "测量", 1.5, 12.0, "m"),
    _s("room.depth_m", 4.0, "physical", "测量", 1.0, 30.0, "m"),
    _s("room.window_face", 2.0, "physical", "1=后 2=右 3=左 4=前", 1, 4, "-"),
    _s("room.window_center_u_m", 0.0, "physical", "开口横向偏移", -15.0, 15.0, "m"),
    _s("room.window_center_v_m", 0.0, "physical", "开口纵向偏移", -6.0, 6.0, "m"),
    _s("room.window_w_m", 1.2, "physical", "窗宽", 0.2, 8.0, "m"),
    _s("room.window_h_m", 1.5, "physical", "窗高", 0.2, 6.0, "m"),
    _s("room.window_frame_ratio", 0.18, "physical", "窗框占比", 0.02, 0.4, "-"),
    _s("room.grid_rows", 3.0, "physical", "窗格行数", 1, 12, "-"),
    _s("room.grid_cols", 2.0, "physical", "窗格列数", 1, 12, "-"),
    _s("room.glass_transmittance", 0.85, "physical", "玻璃透过率", 0.0, 1.0, "-"),
    _s("room.glass_tint_rgb", 1.0, "physical", "玻璃着色", 0.5, 1.0, "-"),
    _s("room.camera_pos_u_m", 0.0, "physical", "相机位置", -15.0, 15.0, "m"),
    _s("room.camera_pos_v_m", 1.5, "physical", "相机高度", 0.2, 6.0, "m"),
    _s("room.camera_fov_deg", 60.0, "physical", "视场角", 10.0, 120.0, "°"),
    _s("room.camera_pitch_deg", 0.0, "physical", "俯仰", -45.0, 45.0, "°"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑧ 材质 / BRDF（15+）
# ═══════════════════════════════════════════════════════════════════
MATERIAL: List[P] = [
    _s("material.albedo", 0.50, "physical", "分光反射率（可见光平均）", 0.0, 1.0, "-"),
    _s("material.albedo_r_ratio", 1.00, "physical", "光谱比 R", 0.5, 1.5, "-"),
    _s("material.albedo_b_ratio", 1.02, "physical", "光谱比 B", 0.5, 1.5, "-"),
    _s("material.roughness", 0.74, "physical", "GGX α", 0.0, 1.0, "-"),
    _s("material.metallic", 0.0, "physical", "金属度", 0.0, 1.0, "-"),
    _s("material.specular_f0", 0.045, "physical", "垂直反射率", 0.0, 1.0, "-"),
    _s("material.ior", 1.50, "physical", "折射率", 1.0, 3.0, "-"),
    _s("material.anisotropy", 0.0, "physical", "各向异性", -1.0, 1.0, "-"),
    _s("material.anisotropy_rot_deg", 0.0, "physical", "各向异性方向", 0.0, 180.0, "°"),
    _s("material.normal_strength", 0.6, "physical", "法线强度", 0.0, 4.0, "-"),
    _s("material.height_scale_mm", 0.5, "physical", "置换高度", 0.0, 20.0, "mm"),
    _s("material.clearcoat", 0.0, "physical", "清漆层", 0.0, 1.0, "-"),
    _s("material.clearcoat_rough", 0.1, "physical", "清漆粗糙度", 0.0, 1.0, "-"),
    _s("material.subsurface", 0.0, "physical", "次表面", 0.0, 1.0, "-"),
    _s("material.sss_radius_mm", 0.5, "physical", "次表面半径", 0.01, 10.0, "mm"),
    _s("material.porosity", 0.15, "physical", "孔隙率（水泥/石膏）", 0.0, 0.6, "-"),
    _s("material.moisture", 0.0, "derived", "含水率（湿面）", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑨ 镜面（15+）
# ═══════════════════════════════════════════════════════════════════
MIRROR: List[P] = [
    _s("mirror.reflectivity", 0.95, "physical", "银镜可见光反射", 0.4, 0.995, "-"),
    _s("mirror.roughness", 0.03, "physical", "微起伏", 0.0, 0.3, "-"),
    _s("mirror.ior", 1.52, "physical", "玻璃基板", 1.4, 1.8, "-"),
    _s("mirror.coating_nm", 120.0, "physical", "镀层厚度", 20, 400, "nm"),
    _s("mirror.second_surface", 0.0, "physical", "1=背面镜", 0.0, 1.0, "-"),
    _s("mirror.tint_r_ratio", 1.0, "physical", "着色 R", 0.7, 1.1, "-"),
    _s("mirror.tint_b_ratio", 1.02, "physical", "着色 B", 0.7, 1.1, "-"),
    _s("mirror.edge_bevel_mm", 2.0, "physical", "边缘倒角", 0.0, 20.0, "mm"),
    _s("mirror.thickness_mm", 5.0, "physical", "玻璃厚度", 2.0, 20.0, "mm"),
    _s("mirror.micro_waviness", 0.05, "physical", "波纹（像变形）", 0.0, 0.5, "-"),
    _s("mirror.dust_coverage", 0.05, "physical", "浮尘覆盖", 0.0, 1.0, "-"),
    _s("mirror.tilt_error_deg", 0.0, "physical", "安装倾斜误差", -3.0, 3.0, "°"),
    _s("mirror.ghost_strength", 0.02, "physical", "二次反射鬼像", 0.0, 0.2, "-"),
    _s("mirror.max_mirror_faces", 3.0, "tunable", "**禁止 6 面全镜面**", 0, 3, "-"),
    _s("mirror.bounce_rays", 1.0, "physical", "单次弹射足够", 1, 4, "-"),
    _s("mirror.text_visibility", 1.0, "derived", "镜中可见文字（含字场景的反射）", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑩ 地面 / 室外（15+）
# ═══════════════════════════════════════════════════════════════════
GROUND: List[P] = [
    _s("ground.albedo_dry", 0.25, "physical", "干燥地面", 0.05, 0.6, "-"),
    _s("ground.albedo_wet", 0.07, "physical", "湿地面", 0.02, 0.2, "-"),
    _s("ground.albedo_snow", 0.80, "physical", "积雪", 0.4, 0.95, "-"),
    _s("ground.roughness", 0.9, "physical", "地面粗糙度", 0.2, 1.0, "-"),
    _s("ground.snow_grain_um", 200.0, "physical", "雪粒半径", 20, 2000, "μm"),
    _s("ground.wet_film_mm", 0.0, "derived", "水膜厚度", 0.0, 3.0, "mm"),
    _s("ground.slope_deg", 0.0, "physical", "坡度", 0.0, 45.0, "°"),
    _s("ground.coverage_frac", 1.0, "physical", "可见地面占比", 0.0, 1.0, "-"),
    _s("ground.vegetation_frac", 0.1, "physical", "植被占比", 0.0, 1.0, "-"),
    _s("ground.urban_frac", 0.2, "physical", "建成区占比", 0.0, 1.0, "-"),
    _s("ground.water_frac", 0.0, "physical", "水面占比", 0.0, 1.0, "-"),
    _s("ground.tree_line_deg", 0.0, "physical", "树线仰角（遮挡）", 0.0, 45.0, "°"),
    _s("ground.far_radiance", 0.02, "derived", "远景辐射（天空光）", 0.0, 4.0, "-"),
    _s("ground.moisture", 0.0, "derived", "表层含水", 0.0, 1.0, "-"),
    _s("ground.temperature_c", 20.0, "derived", "地表温度（热辐射）", -40, 70, "°C"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑪ 夜间光源（15+）
# ═══════════════════════════════════════════════════════════════════
NIGHT: List[P] = [
    _s("night.moon_altitude_deg", 0.0, "derived", "天文算法", -90, 90, "°"),
    _s("night.moon_azimuth_deg", 0.0, "derived", "天文算法", 0, 360, "°"),
    _s("night.moon_phase", 0.5, "derived", "0=新月 0.5=满月", 0.0, 1.0, "-"),
    _s("night.moon_irradiance", 0.0, "derived", "月光辐照度", 0.0, 0.5, "-"),
    _s("night.moon_angular_diameter_deg", 0.5181, "physical", "月亮视直径", 0.49, 0.56, "°"),
    _s("night.moon_color_temp_k", 4100.0, "physical", "月亮色温", 3500, 5000, "K"),
    _s("night.sky_glow", 0.008, "physical", "夜空辉光", 0.0, 0.05, "-"),
    _s("night.star_magnitude_limit", 6.0, "physical", "可见星等", 3.0, 8.0, "-"),
    _s("night.city_glow_dir_deg", 180.0, "physical", "城市光害方向", 0, 360, "°"),
    _s("night.city_glow_intensity", 0.02, "physical", "城市光害强度", 0.0, 0.3, "-"),
    _s("night.light_pollution_color_r", 0.9, "derived", "钠灯偏暖", 0.5, 1.0, "-"),
    _s("night.light_pollution_color_b", 0.7, "derived", "钠灯偏暖", 0.3, 1.0, "-"),
    _s("night.airglow_line_nm", 557.7, "physical", "氧绿线", 550, 640, "nm"),
    _s("night.milkyway_strength", 0.0, "physical", "银河亮度", 0.0, 1.0, "-"),
    _s("night.meteor_rate_per_h", 0.0, "physical", "流星频率", 0.0, 120.0, "1/h"),
    _s("night.snow_glow_gain", 0.35, "derived", "雪地反照率增益", 0.0, 0.9, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑫ 光传输（15+）
# ═══════════════════════════════════════════════════════════════════
TRANSPORT: List[P] = [
    _s("transport.max_bounces", 2.0, "physical", "间接弹射次数", 0, 8, "-"),
    _s("transport.radiosity_patches", 12.0, "tunable", "每面分片 12x12", 2, 64, "-"),
    _s("transport.form_factor_model", 1.0, "physical", "1=解析 2=采样", 1, 2, "-"),
    _s("transport.sky_samples_az", 36.0, "tunable", "穹顶方位采样", 8, 256, "-"),
    _s("transport.sky_samples_el", 9.0, "tunable", "穹顶仰角采样", 4, 128, "-"),
    _s("transport.sun_disc_samples", 9.0, "tunable", "太阳圆盘采样（半影）", 1, 64, "-"),
    _s("transport.penumbra_samples", 9.0, "physical", "软阴影条带数", 3, 33, "-"),
    _s("transport.ao_radius_m", 0.5, "physical", "环境光遮蔽半径", 0.05, 5.0, "m"),
    _s("transport.ao_samples", 16.0, "tunable", "AO 采样数", 4, 128, "-"),
    _s("transport.energy_eps", 0.001, "tunable", "能量守恒容差", 1e-6, 0.05, "-"),
    _s("transport.throughput_clamp", 8.0, "physical", "通量上限（防炸）", 1.0, 64.0, "-"),
    _s("transport.russian_roulette", 0.0, "physical", "1=开启", 0.0, 1.0, "-"),
    _s("transport.indirect_gain", 1.0, "derived", "互反射 k=ρ/(1-ρ)", 0.0, 3.0, "-"),
    _s("transport.room_reflectance", 0.55, "physical", "室内平均反射率", 0.2, 0.85, "-"),
    _s("transport.deterministic_seed", 20260926.0, "physical", "可复现", 0, 1e9, "-"),
    _s("transport.parallel_jobs", 4.0, "tunable", "并行帧数（错峰启动）", 1, 32, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑬ 相机 / 成像（15+）
# ═══════════════════════════════════════════════════════════════════
CAMERA: List[P] = [
    _s("camera.sensor_width_mm", 36.0, "physical", "全画幅", 4.0, 100.0, "mm"),
    _s("camera.sensor_height_mm", 20.25, "physical", "16:9 裁切", 3.0, 80.0, "mm"),
    _s("camera.pixel_pitch_um", 4.3, "physical", "像元尺寸", 1.0, 20.0, "μm"),
    _s("camera.focal_length_mm", 35.0, "physical", "等效焦距", 8.0, 200.0, "mm"),
    _s("camera.aperture_f", 5.6, "physical", "光圈", 0.95, 32.0, "-"),
    _s("camera.shutter_s", 0.008, "physical", "快门", 1e-5, 30.0, "s"),
    _s("camera.iso", 100.0, "physical", "感光度", 25, 409600, "-"),
    _s("camera.exposure_ev", 1.0, "derived", "曝光适应", 0.1, 8.0, "-"),
    _s("camera.white_balance_k", 6500.0, "physical", "白平衡", 2000, 15000, "K"),
    _s("camera.black_point", 0.0, "physical", "黑电平", 0.0, 0.1, "-"),
    _s("camera.highlight_rolloff", 0.8, "physical", "高光滚降", 0.0, 1.0, "-"),
    _s("camera.vignette_strength", 0.15, "physical", "渐晕（光学）", 0.0, 0.6, "-"),
    _s("camera.chromatic_aberration_um", 1.0, "physical", "色差", 0.0, 10.0, "μm"),
    _s("camera.sensor_snr_db", 45.0, "physical", "信噪比", 20, 70, "dB"),
    _s("camera.diffraction_limit", 0.0, "derived", "艾里斑（小光圈）", 0.0, 1.0, "-"),
    _s("camera.rolling_shutter", 0.0, "physical", "卷帘（运动畸变）", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑭ 裂缝 / 污渍 / 年代（15+）
# ═══════════════════════════════════════════════════════════════════
DEFECT: List[P] = [
    _s("defect.crack_density", 0.0, "derived", "自动检测：单位面积长度", 0.0, 5.0, "1/m"),
    _s("defect.crack_width_px", 2.0, "derived", "检测宽度", 1.0, 40.0, "px"),
    _s("defect.crack_depth_ratio", 0.3, "derived", "光渗深度", 0.0, 1.0, "-"),
    _s("defect.crack_orientation_deg", 0.0, "derived", "主方向", 0.0, 180.0, "°"),
    _s("defect.crack_contrast", 0.35, "derived", "对比度", 0.0, 1.0, "-"),
    _s("defect.detection_sigma", 2.0, "tunable", "Hessian/黑帽尺度", 0.5, 8.0, "-"),
    _s("defect.detection_threshold", 0.06, "tunable", "检出阈值", 0.001, 0.5, "-"),
    _s("defect.stain_area_frac", 0.0, "derived", "污渍面积占比", 0.0, 1.0, "-"),
    _s("defect.stain_softness", 0.5, "derived", "边缘柔度", 0.0, 1.0, "-"),
    _s("defect.efflorescence", 0.0, "derived", "泛碱（白霜）", 0.0, 1.0, "-"),
    _s("defect.mold_darkness", 0.0, "derived", "霉斑压暗", 0.0, 1.0, "-"),
    _s("defect.peel_ratio", 0.0, "derived", "起皮占比", 0.0, 1.0, "-"),
    _s("defect.rust_ratio", 0.0, "derived", "锈斑占比", 0.0, 1.0, "-"),
    _s("defect.dust_coverage", 0.05, "derived", "浮尘覆盖", 0.0, 1.0, "-"),
    _s("defect.aged_strength", 0.5, "derived", "年代感总强度", 0.0, 1.0, "-"),
    _s("defect.seep_gain", 0.35, "derived", "裂缝光渗增益", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑮ 叠字 / 墨水 / 颜料（15+）
# ═══════════════════════════════════════════════════════════════════
INK: List[P] = [
    _s("ink.text_len_chars", 3.0, "derived", "文案长度", 0.0, 200.0, "-"),
    _s("ink.font_size_ratio", 0.22, "derived", "字号/画面高", 0.02, 0.6, "-"),
    _s("ink.line_gap_ratio", 0.15, "physical", "行距/字号", 0.0, 1.0, "-"),
    _s("ink.tracking_ratio", 0.0, "physical", "字距", -0.1, 0.5, "-"),
    _s("ink.ink_density", 1.0, "derived", "**墨水浓度**（alpha 峰值）", 0.2, 2.0, "-"),
    _s("ink.ink_saturation", 1.0, "derived", "颜料饱和度", 0.0, 2.0, "-"),
    _s("ink.pigment_r", 0.52, "physical", "颜料反射 R（朱砂）", 0.0, 1.0, "-"),
    _s("ink.pigment_g", 0.055, "physical", "颜料反射 G", 0.0, 1.0, "-"),
    _s("ink.pigment_b", 0.048, "physical", "颜料反射 B", 0.0, 1.0, "-"),
    _s("ink.brush_softness", 0.15, "physical", "笔锋柔度", 0.0, 1.0, "-"),
    _s("ink.diffusion_amp", 0.20, "physical", "颜料扩散幅度", 0.0, 1.0, "-"),
    _s("ink.diffusion_ratio", 0.0018, "physical", "扩散半径/画面高", 0.0, 0.05, "-"),
    _s("ink.edge_erode_ratio", 0.0015, "physical", "边缘侵蚀", 0.0, 0.05, "-"),
    _s("ink.oxidation_dots", 0.0001, "physical", "氧化颗粒密度", 0.0, 0.01, "-"),
    _s("ink.oxidation_amp", 0.30, "physical", "氧化颗粒幅度", 0.0, 1.0, "-"),
    _s("ink.material_coupling", 0.4, "physical", "与墙面材质耦合", 0.0, 1.0, "-"),
    _s("ink.contact_shadow_len", 0.001, "physical", "接触阴影长度/画高", 0.0, 0.05, "-"),
    _s("ink.contact_shadow_strength", 0.25, "physical", "接触阴影强度", 0.0, 1.0, "-"),
]

# ═══════════════════════════════════════════════════════════════════
# ⑯ 色彩 / 色调映射 / 输出（15+）
# ═══════════════════════════════════════════════════════════════════
COLOR: List[P] = [
    _s("color.working_space", 1.0, "physical", "1=linear-sRGB", 1, 3, "-"),
    _s("color.bit_depth", 16.0, "physical", "内部位深", 8, 32, "-"),
    _s("color.tonemap_kind", 1.0, "physical", "1=ACES 2=Reinhard", 1, 3, "-"),
    _s("color.aces_gain", 1.25, "tunable", "ACES 输入增益", 0.5, 3.0, "-"),
    _s("color.s_curve_gain", 0.30, "tunable", "硬度→对比度", 0.0, 1.0, "-"),
    _s("color.eye_adapt_gamma", 0.40, "tunable", "视觉适应幂律", 0.2, 0.8, "-"),
    _s("color.adaptation_ref", 1.0, "physical", "参考照度（晴正午）", 0.1, 10.0, "-"),
    _s("color.saturation_gain", 1.0, "derived", "湿面/雾", 0.5, 1.5, "-"),
    _s("color.cool_shift", 0.0, "derived", "冷偏", -0.2, 0.2, "-"),
    _s("color.shadow_tint_blue", 0.06, "physical", "暗部偏蓝（散射）", 0.0, 0.3, "-"),
    _s("color.highlight_warmth", 0.02, "physical", "高光暖度", -0.1, 0.1, "-"),
    _s("color.filmic_white_nits", 200.0, "physical", "白点（显示器）", 80, 1000, "nit"),
    _s("color.gamut_clip", 1.0, "physical", "1=软截断", 1, 2, "-"),
    _s("color.dither", 1.0, "physical", "输出抖动", 0, 1, "-"),
    _s("color.output_format", 1.0, "physical", "1=PNG 2=JPEG 3=TIFF", 1, 3, "-"),
    _s("color.jpeg_quality", 92.0, "physical", "JPEG 质量", 60, 100, "-"),
]


# ═══════════════════════════════════════════════════════════════════
# ⑰ 性能预算 / 工程（15+）—— 用户硬指标：冷启动≤90s、连产≤10s/张
# ═══════════════════════════════════════════════════════════════════
PERF: List[P] = [
    _s("perf.cold_start_budget_s", 90.0, "physical", "冷启动→首图（用户指标）", 5.0, 600.0, "s"),
    _s("perf.per_photo_budget_s", 10.0, "physical", "连续构建（用户指标）", 0.5, 120.0, "s"),
    _s("perf.cache_hit_budget_ms", 300.0, "physical", "缓存命中路径上限", 10.0, 3000.0, "ms"),
    _s("perf.scene_build_budget_ms", 300.0, "physical", "SceneSpec→脚本上限", 10.0, 3000.0, "ms"),
    _s("perf.model_budget_s", 30.0, "physical", "参数化建模上限（缓存未命中）", 1.0, 300.0, "s"),
    _s("perf.import_budget_ms", 1500.0, "physical", "模块导入上限", 100.0, 10000.0, "ms"),
    _s("perf.encode_budget_ms", 800.0, "physical", "PNG 编码上限（2K）", 50.0, 10000.0, "ms"),
    _s("perf.blender_samples_low", 32.0, "tunable", "快速档采样", 4, 512, "-"),
    _s("perf.blender_samples_mid", 128.0, "tunable", "标准档采样", 16, 2048, "-"),
    _s("perf.blender_samples_high", 512.0, "tunable", "精修档采样", 64, 8192, "-"),
    _s("perf.render_pixels_budget", 2073600.0, "physical", "单帧像素上限（1080p）", 921600.0, 3.3e7, "px"),
    _s("perf.max_workers", 4.0, "tunable", "并行帧数（错峰启动）", 1, 32, "-"),
    _s("perf.io_read_mb_s", 200.0, "physical", "磁盘读取带宽（估）", 5.0, 5000.0, "MB/s"),
    _s("perf.texture_size_px", 2048.0, "physical", "材质贴图边长", 256, 8192, "px"),
    _s("perf.radiosity_budget_ms", 200.0, "physical", "互反射解算上限", 1.0, 5000.0, "ms"),
    _s("perf.sky_integral_budget_ms", 100.0, "physical", "穹顶积分上限", 1.0, 5000.0, "ms"),
]


# ═══════════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════════
ASPECTS: Dict[str, List[P]] = {
    "sun": SUN, "sky": SKY, "cloud": CLOUD, "atmos": ATMOS,
    "precip": PRECIP, "geo": GEO, "room": ROOM, "material": MATERIAL,
    "mirror": MIRROR, "ground": GROUND, "night": NIGHT,
    "transport": TRANSPORT, "camera": CAMERA, "defect": DEFECT,
    "ink": INK, "color": COLOR, "perf": PERF,
}

# 允许"风格手调"的参数白名单（agent.md §11：≤5 个）
TUNABLE_WHITELIST = [
    "sky.dome_n_az", "sky.dome_n_el",          # 采样精度（速度折中）
    "transport.radiosity_patches",             # 互反射分辨率
    "transport.sky_samples_az", "transport.sky_samples_el",
    "transport.sun_disc_samples", "transport.ao_samples",
    "transport.energy_eps",                    # 数值容差（工程）
    "transport.parallel_jobs",                 # 并行度（机器相关）
    "defect.detection_sigma", "defect.detection_threshold",
    "color.aces_gain", "color.s_curve_gain", "color.eye_adapt_gamma",
    "precip.film_ref_mm", "mirror.max_mirror_faces",
]
# 注：上表是**工程/数值**参数（分辨率、阈值、机器并行度），
# 不是"某种天气=某种亮度"的风格旋钮 —— 后者永久禁止。


def all_params() -> Dict[str, P]:
    out: Dict[str, P] = {}
    for name, lst in ASPECTS.items():
        for p in lst:
            if p.key in out:
                raise KeyError("参数键重复：%s" % p.key)
            out[p.key] = p
    return out


def aspect_counts() -> Dict[str, int]:
    return {k: len(v) for k, v in ASPECTS.items()}


def get(key: str) -> Optional[P]:
    return all_params().get(key)


def defaults(aspect: Optional[str] = None) -> Dict[str, float]:
    items = ASPECTS.get(aspect, []) if aspect else all_params().values()
    return {p.key: p.default for p in items}


def validate() -> List[str]:
    """返回问题列表（空 = 通过）。"""
    bad: List[str] = []
    seen = set()
    for name, lst in ASPECTS.items():
        if len(lst) < 15:
            bad.append("方面 %s 只有 %d 个参数（要求 ≥15）" % (name, len(lst)))
        for p in lst:
            if p.key in seen:
                bad.append("键重复：%s" % p.key)
            seen.add(p.key)
            if not (p.lo <= p.default <= p.hi):
                bad.append("%s 默认值 %g 越界 [%g, %g]"
                           % (p.key, p.default, p.lo, p.hi))
            if p.lo > p.hi:
                bad.append("%s 范围颠倒 lo>hi" % p.key)
            if p.kind not in ("physical", "derived", "tunable"):
                bad.append("%s 未知 kind=%s" % (p.key, p.kind))
    for p in all_params().values():
        if p.kind == "tunable" and p.key not in TUNABLE_WHITELIST:
            bad.append("未列入白名单的 tunable：%s" % p.key)
    return bad


def _self_test():                                            # pragma: no cover
    c = aspect_counts()
    print("方面数 %d，参数总数 %d" % (len(c), sum(c.values())))
    print("各方面参数数：")
    for k, v in c.items():
        print("  %-10s %2d  %s" % (k, v, "✅" if v >= 15 else "❌ 不足 15"))
    print("校验：", validate() or "通过")
    tun = [k for k, p in all_params().items() if p.kind == "tunable"]
    print("工程/数值参数（tunable）共 %d 个" % len(tun))


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()