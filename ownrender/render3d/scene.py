#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SceneSpec —— **后端无关**的场景描述（渲染中间层）。

为什么要有它
══════════════════════════════════════════════════════════════════════
渲染后端会换（Blender / Mitsuba / 自研光追），但**参数与几何描述必须只有一份**。
所以：SceneSpec（我们写）→ 各后端只做"翻译"（几十行），不各写一套物理。

支持的"任意墙面"
    · 面 = 任意平面四边形（法线任意）→ 斜墙 / 天花板 / 地板 / 斜切面全都行
    · 材质 = PBR（albedo/roughness/metallic/ior/transmission）
    · **水膜**：单独一层（厚度 / 粗糙度 / IOR=1.33）→ 水渍/水痕/湿面
    · 贴图/掩膜：可选 albedo 贴图、roughness 掩膜、法线贴图（照片或程序化生成）
    · 叠字目标：`text_target=True` 的面可以被投影文字（3D 文本或后融合）
"""
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

D2R = math.pi / 180.0


def _v(x) -> List[float]:
    return [float(a) for a in np.asarray(x, dtype=np.float64).reshape(-1)]


# ═══════════════════════════════════════════════════════════════════
# 基础
# ═══════════════════════════════════════════════════════════════════
@dataclass
class MaterialSpec:
    """PBR 材质（物理量）。"""
    name: str = "plaster"
    albedo: Tuple[float, float, float] = (0.55, 0.55, 0.56)
    roughness: float = 0.70
    metallic: float = 0.0
    ior: float = 1.50
    specular: float = 0.5          # 0.5 = 4% F0（Blender 约定）
    transmission: float = 0.0      # 1 = 玻璃/水
    alpha: float = 1.0
    # 贴图/掩膜（可选，路径或程序化 key）
    albedo_map: Optional[str] = None
    roughness_map: Optional[str] = None
    normal_map: Optional[str] = None
    normal_strength: float = 0.6


@dataclass
class WaterFilm:
    """水膜（水渍/水痕/湿面）：单独一层，物理参数齐全。"""
    enabled: bool = False
    thickness_mm: float = 0.2
    roughness: float = 0.05
    ior: float = 1.333              # 20℃ 水
    coverage: float = 1.0           # 覆盖率（掩膜）
    coverage_map: Optional[str] = None
    wet_darkening: float = 0.28     # 湿面压暗（Kubelka-Munk 近似）


@dataclass
class Quad:
    """任意平面四边形（法线任意 → 支持倾斜墙面）。

    center/u/v 三者定义平面；size_u/size_v 是沿 u/v 的边长（米）。
    """
    name: str
    center: Sequence[float]
    u: Sequence[float]
    v: Sequence[float]
    size_u: float
    size_v: float
    material: MaterialSpec = field(default_factory=MaterialSpec)
    water: WaterFilm = field(default_factory=WaterFilm)
    text_target: bool = False        # 是否作为叠字目标面

    @property
    def normal(self) -> List[float]:
        n = np.cross(np.asarray(self.u, float), np.asarray(self.v, float))
        nn = np.linalg.norm(n)
        return _v(n / (nn if nn > 1e-12 else 1.0))

    def corners(self) -> List[List[float]]:
        c = np.asarray(self.center, float)
        u = np.asarray(self.u, float) * self.size_u
        v = np.asarray(self.v, float) * self.size_v
        return [_v(c - u / 2 - v / 2), _v(c + u / 2 - v / 2),
                _v(c + u / 2 + v / 2), _v(c - u / 2 + v / 2)]


@dataclass
class SunSpec:
    """太阳 = 面光源（角直径决定阴影软硬）。"""
    azimuth_deg: float = 180.0
    altitude_deg: float = 45.0
    angular_diameter_deg: float = 0.5334
    irradiance: float = 1.0               # 相对（与场景单位无关）
    color_rgb: Tuple[float, float, float] = (1.0, 0.96, 0.92)
    distance_au: float = 1.0


@dataclass
class SkySpec:
    """天空 = 穹顶（半球面光源）。"""
    kind: str = "overcast"                # overcast / clear / haze
    diffuse_horizontal: float = 0.19      # 与天气模型能量一致
    zenith_radiance: float = 0.082
    ground_reflectance: float = 0.25
    night_glow: float = 0.0
    stars: float = 0.0
    use_texture: bool = False             # 用后端内置天空纹理（Nishita）
    turbidity: float = 2.5


@dataclass
class CameraSpec:
    position: Sequence[float] = (0.0, 1.5, 3.0)
    look_at: Sequence[float] = (0.0, 1.5, 0.0)
    focal_length_mm: float = 35.0
    sensor_width_mm: float = 36.0
    aperture_f: float = 5.6
    shutter_s: float = 0.008
    iso: float = 100.0
    exposure_ev: float = 1.0
    white_balance_k: float = 6500.0


@dataclass
class RenderSpec:
    engine: str = "CYCLES"                 # CYCLES / BLENDER_EEVEE_NEXT（不推荐）
    device: str = "CPU"
    samples: int = 64
    use_denoise: bool = True
    resolution: Tuple[int, int] = (1920, 1080)
    film_exposure: float = 1.0
    view_transform: str = "AgX"            # AgX / Filmic / Standard
    transparent_film: bool = False


@dataclass
class SceneSpec:
    """完整场景：面 + 光源 + 相机 + 渲染设置。"""
    name: str = "ownrender-scene"
    quads: List[Quad] = field(default_factory=list)
    sun: SunSpec = field(default_factory=SunSpec)
    sky: SkySpec = field(default_factory=SkySpec)
    camera: CameraSpec = field(default_factory=CameraSpec)
    render: RenderSpec = field(default_factory=RenderSpec)
    seed: int = 20260926
    notes: str = ""

    # ── 便捷构造：从房间（6 面 + 开口）生成 ─────────────────────
    @classmethod
    def from_room(cls, room, text_face: str = "back", **kw) -> "SceneSpec":
        quads = []
        for name, f in room.faces.items():
            m = f.material
            quads.append(Quad(
                name=name, center=_v(f.center), u=_v(f.u), v=_v(f.v),
                size_u=float(f.size_u), size_v=float(f.size_v),
                material=MaterialSpec(
                    name=m.name, albedo=tuple(m.albedo),
                    roughness=float(m.roughness),
                    ior=float(getattr(m, "ior", 1.5)),
                    specular=0.5 if m.specular <= 0.05 else 0.9),
                text_target=(name == text_face)))
        spec = cls(quads=quads, **kw)
        return spec

    # ── 校验 ────────────────────────────────────────────────────
    def validate(self) -> List[str]:
        bad: List[str] = []
        if not self.quads:
            bad.append("场景没有任何面")
        for q in self.quads:
            n = np.asarray(q.u, float)
            v = np.asarray(q.v, float)
            if abs(float(n @ v)) > 1e-6:
                bad.append("%s: u·v != 0（u/v 必须正交）" % q.name)
            if q.size_u <= 0 or q.size_v <= 0:
                bad.append("%s: 尺寸必须为正" % q.name)
            if not (0.0 <= q.material.roughness <= 1.0):
                bad.append("%s: roughness 越界" % q.name)
            if not (1.0 <= q.material.ior <= 3.0):
                bad.append("%s: ior 越界" % q.name)
            if q.water.enabled and not (1.0 <= q.water.ior <= 1.5):
                bad.append("%s: 水膜 ior 越界" % q.name)
        if self.sun.angular_diameter_deg <= 0:
            bad.append("太阳角直径必须 > 0（面光源）")
        if self.render.samples < 1:
            bad.append("采样数必须 ≥ 1")
        mirrors = [q.name for q in self.quads
                   if q.material.roughness <= 0.1 and q.material.specular >= 0.9]
        if len(mirrors) >= 6:
            bad.append("6 个面全是镜面（物理不可能）：%s" % ",".join(mirrors))
        return bad

    # ── 序列化（给后端/缓存用）──────────────────────────────────
    def to_dict(self) -> Dict:
        d = {
            "name": self.name, "seed": self.seed, "notes": self.notes,
            "sun": asdict(self.sun), "sky": asdict(self.sky),
            "camera": asdict(self.camera), "render": asdict(self.render),
            "quads": [],
        }
        for q in self.quads:
            qd = asdict(q)
            qd["normal"] = self.normal_of(q)
            qd["corners"] = q.corners()
            d["quads"].append(qd)
        return d

    @staticmethod
    def normal_of(q: Quad) -> List[float]:
        return q.normal

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    # ── 统计（给日志/文档）──────────────────────────────────────
    def summary(self) -> str:
        n_water = sum(1 for q in self.quads if q.water.enabled)
        n_text = sum(1 for q in self.quads if q.text_target)
        return ("面 %d（水膜 %d，叠字目标 %d）｜太阳 alt=%.1f° 视直径=%.4f°"
                "｜天空 %s｜%dx%d %d spp %s"
                % (len(self.quads), n_water, n_text,
                   self.sun.altitude_deg, self.sun.angular_diameter_deg,
                   self.sky.kind, self.render.resolution[0],
                   self.render.resolution[1], self.render.samples,
                   self.render.engine))


def _self_test():                                            # pragma: no cover
    from ownrender.scene3d.room import Room
    r = Room(4.0, 3.0, 4.0)
    r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    s = SceneSpec.from_room(r, text_face="back")
    print(s.summary())
    print("校验：", s.validate() or "通过")
    for q in s.quads[:2]:
        print("  %-6s normal=%s corners=%d" % (q.name, q.normal, len(q.corners())))


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()