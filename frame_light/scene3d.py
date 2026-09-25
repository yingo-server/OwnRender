#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架 — 3D 场景建模

职责：
  1. Scene3D 类：房间 + 窗户 + 相机的 3D 定义
  2. 屏幕坐标 → 世界射线（逐像素）
  3. 射线与观察墙求交
  4. 射线与窗户矩形求交（含窗格遮挡判断）
  5. 太阳方向 → 房间坐标系光线方向

坐标系统（右手系）：
  +X：屏幕右（地理东）
  +Y：屏幕上
  +Z：朝相机（地理南）

  观察墙：z = 0 平面，法线 +Z 朝向相机
  相机：看向 -Z，位于 cam_pos
  窗户：右侧墙 x = +room_w/2，或左侧墙 x = -room_w/2

不 import 本框架其他文件。
只 import 标准库 + numpy + config。
被 raytrace.py 使用。
"""
import math
from typing import Optional, Tuple

import numpy as np

import config


# ═══════════════════════════════════════════════════════════════════
# Scene3D
# ═══════════════════════════════════════════════════════════════════
class Scene3D:
    """
    3D 场景：房间 + 窗户 + 相机。
    屏幕坐标系通过 set_image_size 关联。
    """

    def __init__(self, cfg: dict = None):
        if cfg is None:
            cfg = config.get_lighting().get("scene", {})

        # ── 房间尺寸（米） ──
        self.room_w = float(cfg.get("room_w_m", 4.0))
        self.room_h = float(cfg.get("room_h_m", 3.0))
        self.room_d = float(cfg.get("room_d_m", 4.0))

        # ── 窗户（侧面墙上的开口） ──
        self.win_side = cfg.get("window_side", "right")
        self.win_w = float(cfg.get("window_w_m", 1.2))
        self.win_h = float(cfg.get("window_h_m", 1.5))
        self.win_cy = float(cfg.get("window_cy_m", 1.5))
        self.win_cz = float(cfg.get("window_cz_m", 1.5))

        # ── 窗户分格 ──
        self.grid_rows = max(1, int(cfg.get("grid_rows", 3)))
        self.grid_cols = max(1, int(cfg.get("grid_cols", 2)))
        self.grid_frame_ratio = float(cfg.get("grid_frame_ratio", 0.10))
        self.grid_frame_ratio = max(0.02, min(0.40, self.grid_frame_ratio))

        # ── 相机 ──
        self.cam_pos = np.array(
            cfg.get("camera_pos_m", [0.0, 1.5, 3.0]), dtype=np.float64)
        self.cam_fov = float(cfg.get("camera_fov_deg", 60))

        # ── 图像尺寸 ──
        self.W = 0
        self.H = 0
        self.aspect = 1.0

    # ─────────────────────────────────────────────────────────────
    def set_image_size(self, W: int, H: int):
        """绑定图像尺寸。"""
        self.W = int(W)
        self.H = int(H)
        self.aspect = W / H if H > 0 else 1.0

    # ─────────────────────────────────────────────────────────────
    @property
    def win_x(self) -> float:
        """窗户所在平面的 x 坐标。"""
        return (self.room_w / 2.0 if self.win_side == "right"
                else -self.room_w / 2.0)

    @property
    def win_bbox(self) -> Tuple[float, float, float, float]:
        """窗户矩形边界 (y0, y1, z0, z1)。"""
        y0 = self.win_cy - self.win_w / 2
        y1 = self.win_cy + self.win_w / 2
        z0 = self.win_cz - self.win_h / 2
        z1 = self.win_cz + self.win_h / 2
        return y0, y1, z0, z1

    # ─────────────────────────────────────────────────────────────
    def screen_to_ray(self, px: float, py: float):
        """单像素：屏幕坐标 → 世界射线。"""
        if self.W == 0 or self.H == 0:
            raise ValueError("set_image_size 未调用")

        nx = 2.0 * px / max(self.W - 1, 1) - 1.0
        ny = 1.0 - 2.0 * py / max(self.H - 1, 1)

        tan_half = math.tan(math.radians(self.cam_fov * 0.5))
        dir_cam = np.array([
            nx * tan_half * self.aspect,
            ny * tan_half,
            -1.0,
        ], dtype=np.float64)
        dir_world = dir_cam / np.linalg.norm(dir_cam)

        return self.cam_pos.copy(), dir_world

    # ─────────────────────────────────────────────────────────────
    def screen_to_ray_batch(self, W: int, H: int):
        """批量：屏幕网格 → 世界射线。"""
        if self.W == 0 or self.H == 0:
            raise ValueError("set_image_size 未调用")

        xs = np.linspace(0.0, 1.0, W)
        ys = np.linspace(0.0, 1.0, H)
        xx, yy = np.meshgrid(xs, ys)

        nx = 2.0 * xx - 1.0
        ny = 1.0 - 2.0 * yy

        tan_half = math.tan(math.radians(self.cam_fov * 0.5))

        dirs = np.stack([
            nx * tan_half * self.aspect,
            ny * tan_half,
            -np.ones_like(nx),
        ], axis=-1).astype(np.float64)

        norm = np.linalg.norm(dirs, axis=-1, keepdims=True)
        dirs = dirs / np.maximum(norm, 1e-12)

        origins = np.broadcast_to(
            self.cam_pos, (H, W, 3)).astype(np.float64).copy()

        return origins, dirs

    # ─────────────────────────────────────────────────────────────
    def ray_wall_intersect_batch(self, origins, dirs):
        """批量射线与观察墙 (z = 0) 求交。"""
        z0 = origins[..., 2]
        dz = dirs[..., 2]

        with np.errstate(divide='ignore', invalid='ignore'):
            t = np.where(np.abs(dz) > 1e-9, -z0 / dz, -1.0)

        hit = t > 0
        t_exp = t[..., None]
        P = origins + t_exp * dirs

        return hit, P

    # ─────────────────────────────────────────────────────────────
    # 窗户可见性（含窗格）
    # ─────────────────────────────────────────────────────────────
    def _is_in_net_area_batch(self, y_in: np.ndarray,
                               z_in: np.ndarray) -> np.ndarray:
        """
        判断窗户内的相对位置 (y_in, z_in) ∈ [0,1]×[0,1] 是否在
        【某个窗格的净区域】内。
        """
        # 物理格尺寸
        cell_w = self.win_w / self.grid_cols
        cell_h = self.win_h / self.grid_rows
        cell_short = min(cell_w, cell_h)

        # 窗框宽度（物理单位）
        frame = self.grid_frame_ratio * cell_short
        half = frame * 0.5

        # 转物理坐标
        y_phys = y_in * self.win_w
        z_phys = z_in * self.win_h

        # 所在格子索引（clip 保护越界）
        col = np.floor(y_phys / max(cell_w, 1e-6)).astype(np.int32)
        col = np.clip(col, 0, self.grid_cols - 1)
        row = np.floor(z_phys / max(cell_h, 1e-6)).astype(np.int32)
        row = np.clip(row, 0, self.grid_rows - 1)

        # 格子内局部坐标
        y_local = y_phys - col * cell_w
        z_local = z_phys - row * cell_h

        # 净区域判断
        in_y = (y_local >= half) & (y_local <= cell_w - half)
        in_z = (z_local >= half) & (z_local <= cell_h - half)

        return in_y & in_z

    # ─────────────────────────────────────────────────────────────
    def is_visible_through_window(self, P: np.ndarray,
                                   sun_dir: np.ndarray) -> bool:
        """单点：从 P 沿 -sun_dir 追到窗户平面，判断是否可见。"""
        if abs(sun_dir[0]) < 1e-9:
            return False

        t = (P[0] - self.win_x) / sun_dir[0]
        if t <= 0:
            return False

        Q = P - t * sun_dir

        y0, y1, z0, z1 = self.win_bbox
        if not (y0 <= Q[1] <= y1 and z0 <= Q[2] <= z1):
            return False

        # 窗格判断
        y_in = (Q[1] - y0) / max(self.win_w, 1e-6)
        z_in = (Q[2] - z0) / max(self.win_h, 1e-6)
        in_net = self._is_in_net_area_batch(
            np.array(y_in, dtype=np.float64),
            np.array(z_in, dtype=np.float64))
        return bool(np.asarray(in_net).item())

    # ─────────────────────────────────────────────────────────────
    def is_visible_through_window_batch(self, P: np.ndarray,
                                         sun_dir: np.ndarray):
        """
        批量：可见性判断（含窗格）。
        返回：
          visible: (H, W) bool
          Q:       (H, W, 3) 交点
        """
        H, W = P.shape[:2]

        if abs(sun_dir[0]) < 1e-9:
            return np.zeros((H, W), dtype=bool), P.copy()

        t = (P[..., 0] - self.win_x) / sun_dir[0]
        t_valid = t > 0

        t_exp = t[..., None]
        Q = P - t_exp * sun_dir[None, None, :]

        y0, y1, z0, z1 = self.win_bbox
        in_y = (Q[..., 1] >= y0) & (Q[..., 1] <= y1)
        in_z = (Q[..., 2] >= z0) & (Q[..., 2] <= z1)
        in_window = t_valid & in_y & in_z

        # 窗格判断
        y_in = (Q[..., 1] - y0) / max(self.win_w, 1e-6)
        z_in = (Q[..., 2] - z0) / max(self.win_h, 1e-6)

        in_net = self._is_in_net_area_batch(y_in, z_in)

        visible = in_window & in_net
        return visible, Q


# ═══════════════════════════════════════════════════════════════════
# 太阳方向 → 房间坐标
# ═══════════════════════════════════════════════════════════════════
def sun_to_room_dir(sun_az_deg: float, sun_alt_deg: float) -> np.ndarray:
    """地理方位角/高度角 → 房间坐标系下的光线方向（从太阳射向地面）。"""
    az = math.radians(sun_az_deg)
    alt = math.radians(sun_alt_deg)
    cos_alt = math.cos(alt)

    sun_pos = np.array([
        math.sin(az) * cos_alt,      # 东 → +X
        math.sin(alt),               # 上 → +Y
        -math.cos(az) * cos_alt,     # 北 → -Z
    ], dtype=np.float64)

    return -sun_pos


# ═══════════════════════════════════════════════════════════════════
# 便捷
# ═══════════════════════════════════════════════════════════════════
def default_scene() -> Scene3D:
    return Scene3D()


# ═══════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════
def _self_test():
    s = Scene3D()
    s.set_image_size(1920, 1080)

    origin, direction = s.screen_to_ray(960, 540)
    print(f"cam_pos = {origin}")
    print(f"center ray dir = {direction}")

    origins, dirs = s.screen_to_ray_batch(1920, 1080)
    hit, P = s.ray_wall_intersect_batch(origins, dirs)
    print(f"center hit = {hit[540, 960]}, P = {P[540, 960]}")

    print(f"\n窗户分格: {s.grid_rows}行 × {s.grid_cols}列 "
          f"frame={s.grid_frame_ratio}")

    # 窗格测试：窗户内不同位置
    print("\n窗格判断测试（y_in, z_in ∈ [0,1]）：")
    test_points = [
        (0.25, 0.15), (0.25, 0.50), (0.25, 0.85),
        (0.50, 0.15), (0.50, 0.50), (0.50, 0.85),
        (0.75, 0.15), (0.75, 0.50), (0.75, 0.85),
        (0.00, 0.00), (1.00, 1.00),  # 角
    ]
    for y_in, z_in in test_points:
        in_net = s._is_in_net_area_batch(
            np.array(y_in, dtype=np.float64),
            np.array(z_in, dtype=np.float64))
        mark = "亮" if bool(np.asarray(in_net).item()) else "暗(窗框)"
        print(f"  y_in={y_in:.2f} z_in={z_in:.2f} → {mark}")

    print("\nsun_to_room_dir:")
    for az, alt in [(90, 45), (135, 30), (180, 60), (270, 30)]:
        d = sun_to_room_dir(az, alt)
        print(f"  az={az:3d}° alt={alt:2d}° → "
              f"({d[0]:+.3f}, {d[1]:+.3f}, {d[2]:+.3f})")


if __name__ == "__main__":
    _self_test()