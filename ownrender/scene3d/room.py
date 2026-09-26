#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3D 房间：6 个面 + 开口（窗/门）+ 材质。

坐标约定（与现有 frame_light/scene3d.py 保持一致）
    X 右、Y 上、Z 朝相机
    · 观察墙   z = 0，法线 +Z
    · 侧墙     x = ±W/2（窗通常在这面）
    · 地板/天花板 y = 0 / H
    · 房间深度 z ∈ [0, D]

本模块只写**几何与物理**（开口积分、投影立体角、材质校验）；
网格/射线求交这类通用容器若需要，交给 trimesh（可选依赖，缺失则降级）。
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ═══════════════════════════════════════════════════════════════════
# 材质
# ═══════════════════════════════════════════════════════════════════
@dataclass
class Material:
    """材质：只放**物理量**（反照率/粗糙度/折射率/镜面反射率）。"""
    name: str = "plaster"
    albedo: Tuple[float, float, float] = (0.55, 0.55, 0.56)
    roughness: float = 0.70          # 0=镜面，1=完全漫反射
    specular: float = 0.04           # 垂直入射反射率 F0（玻璃 0.04，银 0.95）
    ior: float = 1.50                # 折射率（用于 Fresnel）
    emission: float = 0.0            # 自发光（灯具用，默认 0）

    @property
    def is_mirror(self) -> bool:
        """镜面判定：低粗糙 + 高镜面反射率。"""
        return self.roughness <= 0.10 and self.specular >= 0.50


# 常用材质（材料常数，非风格参数）
MATERIALS: Dict[str, Material] = {
    "plaster":  Material("plaster",  (0.55, 0.55, 0.56), 0.70, 0.04),
    "cement":   Material("cement",   (0.42, 0.43, 0.45), 0.78, 0.05),
    "microcement": Material("microcement", (0.50, 0.50, 0.51), 0.74, 0.045),
    "wood":     Material("wood",     (0.28, 0.18, 0.10), 0.60, 0.05),
    "metal":    Material("metal",    (0.60, 0.60, 0.62), 0.35, 0.60),
    "mirror":   Material("mirror",   (0.92, 0.92, 0.92), 0.03, 0.95),
    "glass":    Material("glass",    (0.90, 0.92, 0.95), 0.02, 0.04, ior=1.52),
}


# ═══════════════════════════════════════════════════════════════════
# 面与开口
# ═══════════════════════════════════════════════════════════════════
@dataclass
class Face:
    """矩形面：平面点 + 两个正交轴 + 尺寸 + 法线。"""
    name: str
    center: np.ndarray               # 面中心（世界坐标）
    u: np.ndarray                    # 局部 u 轴（单位）
    v: np.ndarray                    # 局部 v 轴（单位）
    normal: np.ndarray               # 外法线（单位）
    size_u: float
    size_v: float
    material: Material = field(default_factory=lambda: MATERIALS["plaster"])

    @property
    def area(self) -> float:
        return float(self.size_u * self.size_v)

    def point_at(self, uu: float, vv: float) -> np.ndarray:
        """局部坐标 → 世界坐标。uu/vv ∈ [-0.5, 0.5]。"""
        return (self.center + self.u * (uu * self.size_u)
                + self.v * (vv * self.size_v))

    def sample_grid(self, nu: int, nv: int) -> Tuple[np.ndarray, float]:
        """面采样：(nu*nv, 3) 采样点 + 每点面积权重。"""
        us = (np.arange(nu) + 0.5) / nu - 0.5
        vs = (np.arange(nv) + 0.5) / nv - 0.5
        pts = np.array([self.point_at(u, v) for v in vs for u in us])
        return pts, self.area / float(nu * nv)


@dataclass
class Opening:
    """开口（窗/门）：贴在某个面上的矩形（局部 u/v 坐标）。"""
    face: str
    cu: float = 0.0
    cv: float = 0.0
    size_u: float = 1.2
    size_v: float = 1.5
    kind: str = "window"          # window / door

    @property
    def area(self) -> float:
        return float(self.size_u * self.size_v)


# ═══════════════════════════════════════════════════════════════════
# 房间
# ═══════════════════════════════════════════════════════════════════
class Room:
    """轴对齐房间：6 面 + 若干开口。"""

    def __init__(self, w: float = 4.0, h: float = 3.0, d: float = 4.0,
                 surfaces: Optional[Dict[str, str]] = None):
        self.w, self.h, self.d = float(w), float(h), float(d)
        m = dict(surfaces or {})
        self.faces: Dict[str, Face] = self._build_faces(m)
        self.openings: List[Opening] = []

    # ── 构造 ────────────────────────────────────────────────────
    def _build_faces(self, mats: Dict[str, str]) -> Dict[str, Face]:
        W, H, D = self.w, self.h, self.d

        def mat(key, default="plaster"):
            return MATERIALS.get(mats.get(key, default), MATERIALS[default])

        X, Y, Z = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
        return {
            # 观察墙 z=0，法线 +Z 朝相机
            "back":   Face("back",   np.array([0, H / 2, 0]), X, Y, Z.copy(), W, H, mat("back")),
            # 对面墙 z=D，法线 -Z
            "front":  Face("front",  np.array([0, H / 2, D]), X, Y, -Z, W, H, mat("front")),
            # 左墙 x=-W/2，法线 -X
            "left":   Face("left",   np.array([-W / 2, H / 2, D / 2]), Z, Y, -X, D, H, mat("left")),
            # 右墙 x=+W/2，法线 +X（窗默认在这面）
            "right":  Face("right",  np.array([W / 2, H / 2, D / 2]), Z, Y, X.copy(), D, H, mat("right")),
            # 地板 y=0，法线 +Y
            "floor":  Face("floor",  np.array([0, 0, D / 2]), X, Z, Y.copy(), W, D, mat("floor")),
            # 天花板 y=H，法线 -Y
            "ceil":   Face("ceil",   np.array([0, H, D / 2]), X, Z, -Y, W, D, mat("ceil")),
        }

    def add_window(self, face: str = "right", cu: float = 0.0, cv: float = 0.0,
                   size_u: float = 1.2, size_v: float = 1.5,
                   kind: str = "window") -> Opening:
        op = Opening(face, cu, cv, size_u, size_v, kind)
        self.openings.append(op)
        return op

    # ── 校验（物理可行性，配置阶段就该失败）──────────────────────
    def validate(self) -> List[str]:
        """返回问题列表（空 = 通过）。"""
        bad: List[str] = []
        for name, f in self.faces.items():
            a = f.material.albedo
            if not all(0.0 <= x <= 1.0 for x in a):
                bad.append(f"{name}: albedo 必须在 [0,1]")
            if not 0.0 <= f.material.roughness <= 1.0:
                bad.append(f"{name}: roughness 必须在 [0,1]")
            if not 0.0 <= f.material.specular <= 1.0:
                bad.append(f"{name}: specular 必须在 [0,1]")
        # ★ 禁止"6 面全是镜面"：物理上不可能（镜面互为像，且无共同可见性）
        mirrors = [n for n, f in self.faces.items() if f.material.is_mirror]
        if len(mirrors) >= 6:
            bad.append("6 个面全是镜面（物理不可能）：至少保留一面非镜面")
        elif len(mirrors) >= 4:
            bad.append(f"镜面过多（{len(mirrors)} 面）：%s —— 真人房间不会这样"
                       % ",".join(mirrors))
        for op in self.openings:
            f = self.faces.get(op.face)
            if f is None:
                bad.append(f"开口贴在未知面 {op.face}")
                continue
            if abs(op.cu) + op.size_u / 2 > f.size_u / 2 + 1e-9 or \
               abs(op.cv) + op.size_v / 2 > f.size_v / 2 + 1e-9:
                bad.append(f"开口超出面边界：{op.face} {op.size_u}x{op.size_v}")
        return bad

    # ── 开口辐射积分（面光源；天空/太阳透过窗户都用它）──────────
    def irradiance_from_opening(self, P: np.ndarray, n: np.ndarray,
                                op: Opening,
                                radiance_fn: Callable[[np.ndarray], np.ndarray],
                                samples: Sequence[int] = (6, 5)) -> np.ndarray:
        """开口对面点 P（接收面法线 n，**朝房间内侧**）的照度：
            E = ∫ L(d̂)·cosθ_recv·|cosθ_aper| / r² dA

        两个余弦的约定（之前写成 n·(-d̂) 是错的，会恒为 0）：
          · 接收面： cosθ_recv = max(0, n·d̂)      ← d̂ 由 P 指向开口
          · 开口：   cosθ_aper = |n_win·d̂|        ← 开口是"通光孔"，取投影面积

        radiance_fn(d) 接受**从 P 指向开口并继续向外**的单位方向 d，
        返回该方向的辐射亮度（光谱或标量）—— 天空穹顶就是这么进来的：
        从 P 看窗，每个窗点背后是天空的某个方向。

        全部量都是真实几何：开口面积、两个余弦、1/r²，没有任何手调系数。
        """
        face = self.faces[op.face]
        # ★ 直接在**开口矩形内**采样（面积权重精确 = 窗面积/N）。
        #   之前先采整面墙再筛格子：粗网格下有效面积会偏大（实测 2.4 vs 1.8），
        #   且浪费采样点。
        nu, nv = int(samples[0]), int(samples[1])
        us = (np.arange(nu) + 0.5) / nu - 0.5
        vs = (np.arange(nv) + 0.5) / nv - 0.5
        pts = np.array([
            face.point_at(op.cu + u * op.size_u / face.size_u,
                          op.cv + v * op.size_v / face.size_v)
            for v in vs for u in us])
        dA_eff = op.area / float(nu * nv)

        v = pts - P[None, :]                    # P → 窗点
        r2 = np.sum(v * v, axis=1)
        r = np.sqrt(np.maximum(r2, 1e-12))
        d_hat = v / r[:, None]                  # 单位方向：P → 窗点（并继续向外）
        cos_recv = np.maximum(0.0, (n[None, :] * d_hat).sum(axis=1))
        cos_aper = np.abs((face.normal[None, :] * d_hat).sum(axis=1))

        L = np.asarray(radiance_fn(d_hat), dtype=np.float64)
        if L.ndim == 1:
            L = L[:, None]                      # 标量亮度 → 广播
        w = (cos_recv * cos_aper / r2) * dA_eff
        return (L * w[:, None]).sum(axis=0)

    # ── 序列化（给缓存用）───────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "dims": [self.w, self.h, self.d],
            "materials": {n: {"name": f.material.name,
                              "albedo": list(f.material.albedo),
                              "roughness": f.material.roughness,
                              "specular": f.material.specular,
                              "ior": f.material.ior}
                          for n, f in self.faces.items()},
            "openings": [{"face": o.face, "cu": o.cu, "cv": o.cv,
                          "size_u": o.size_u, "size_v": o.size_v,
                          "kind": o.kind} for o in self.openings],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Room":
        dims = d.get("dims", [4.0, 3.0, 4.0])
        mats = {n: v.get("name", "plaster")
                for n, v in (d.get("materials") or {}).items()}
        room = cls(dims[0], dims[1], dims[2], mats)
        for o in d.get("openings", []):
            room.add_window(o["face"], o["cu"], o["cv"],
                            o["size_u"], o["size_v"], o.get("kind", "window"))
        return room

# ═══════════════════════════════════════════════════════════════════
# 自检（python -m ownrender.scene3d.room）
# ═══════════════════════════════════════════════════════════════════
def _self_test():                                             # pragma: no cover
    r = Room(4.0, 3.0, 4.0)
    r.add_window("right", 0.0, 0.0, 1.2, 1.5)
    print("面面积：", {k: round(f.area, 2) for k, f in r.faces.items()})
    print("校验：", r.validate() or "通过")

    P = np.array([0.0, 1.5, 0.5])
    n = np.array([0.0, 0.0, 1.0])
    E = r.irradiance_from_opening(P, n, r.openings[0],
                                  lambda d: np.ones((len(d), 3)))
    print("常亮(1.0)天空透过窗的照度：", np.round(E, 4))

    # 地板（法线朝上）离窗越远越暗 —— 这才是"距离衰减"的正确检查
    n_floor = np.array([0.0, 1.0, 0.0])
    xs = [0.0, -0.5, -1.0, -1.5]
    Es = []
    for x in xs:
        Es.append(float(r.irradiance_from_opening(
            np.array([x, 0.0, 2.0]), n_floor, r.openings[0],
            lambda d: np.ones((len(d), 3)))[0]))
    print("地板照度随离窗距离：", ["%.4f" % e for e in Es])


if __name__ == "__main__":                                    # pragma: no cover
    _self_test()