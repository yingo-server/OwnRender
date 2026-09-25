#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架 — PBR 五通道材质提取

职责：
  从 Retinex 输出的 R_clean 提取：
    1. albedo   — 漫反射基色 (H, W, 3)，均值≈1
    2. roughness — 微观粗糙度 (H, W)，0~1
    3. normal   — 表面法线 (H, W, 3)，单位向量，z>0
    4. specular — 镜面高光强度 (H, W)，0~1
    5. height   — 相对高度 (H, W)，零均值
    6. is_water — 水面判定 (H, W) bool

物理依据：
  - albedo  : 彩色先验（通道最小值估计 shading 的灰度部分）
  - roughness: 局部方差 / 均值（光滑面方差小）
  - normal  : 亮度梯度（Photometric Stereo 单光源假设）
  - specular: 局部超出周围均值的部分
  - height  : 法线积分
  - is_water: 低 albedo + 低 roughness + 高光滑度

不 import 本框架其他文件。
只 import config + utils（本框架）+ 标准库 + numpy。
被 pipeline.py 编排调用。
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np

import config
from . import utils


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════
@dataclass
class MaterialMaps:
    """PBR 五通道 + 水面 mask。"""
    albedo: np.ndarray      # (H, W, 3) float32
    roughness: np.ndarray   # (H, W)    float32
    normal: np.ndarray      # (H, W, 3) float32（单位向量）
    specular: np.ndarray    # (H, W)    float32
    height: np.ndarray      # (H, W)    float32
    is_water: np.ndarray    # (H, W)    bool

    def stats(self) -> dict:
        """返回统计摘要，用于日志。"""
        a = self.albedo.mean(axis=2)
        return {
            "albedo_mean": float(a.mean()),
            "albedo_min":  float(a.min()),
            "albedo_max":  float(a.max()),
            "roughness_mean": float(self.roughness.mean()),
            "specular_mean":  float(self.specular.mean()),
            "height_range":   float(self.height.max() - self.height.min()),
            "water_ratio":    float(self.is_water.mean()),
        }


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════
def extract_material(R_clean: np.ndarray,
                     cfg: Optional[dict] = None,
                     progress=None) -> MaterialMaps:
    """
    从 R_clean (H, W, 3) 提取 PBR 五通道。

    参数：
      R_clean:  反射率，来自 retinex.decompose_albedo
      cfg:      光照配置（可选）
      progress: 进度条对象（可选）

    返回：
      MaterialMaps
    """
    if cfg is None:
        cfg = config.get_lighting()
    rep = utils.report
    H, W = R_clean.shape[:2]

    # ══════════════════════════════════════════════════════════
    # 阶段 1：Albedo（彩色先验）
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.05, "Albedo（彩色先验）")
    albedo = _extract_albedo(R_clean, cfg)
    rep(progress, 0.20, f"albedo_mean={float(albedo.mean()):.3f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 2：Roughness（局部方差）
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.30, "Roughness（局部方差）")
    roughness = _extract_roughness(albedo, cfg)
    rep(progress, 0.45, f"roughness_mean={float(roughness.mean()):.3f}")

    # ══════════════════════════════════════════════════════════
    # 阶段 3：Normal（亮度梯度）
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.55, "Normal（亮度梯度）")
    normal = _extract_normal(albedo, cfg)

    # ══════════════════════════════════════════════════════════
    # 阶段 4：Specular（局部高光）
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.70, "Specular（局部高光）")
    specular = _extract_specular(albedo, cfg)

    # ══════════════════════════════════════════════════════════
    # 阶段 5：Height（法线积分）
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.82, "Height（法线积分）")
    height = _extract_height(normal, albedo, cfg)

    # ══════════════════════════════════════════════════════════
    # 阶段 6：水面判定
    # ══════════════════════════════════════════════════════════
    rep(progress, 0.92, "水面判定")
    is_water = _detect_water(albedo, roughness, specular, cfg)

    rep(progress, 1.0, "材质提取完成")

    m = MaterialMaps(
        albedo=albedo.astype(np.float32),
        roughness=roughness.astype(np.float32),
        normal=normal.astype(np.float32),
        specular=specular.astype(np.float32),
        height=height.astype(np.float32),
        is_water=is_water,
    )

    s = m.stats()
    config.LOG.param("材质-均值", f"{s['albedo_mean']:.3f}")
    config.LOG.param("材质-范围",
                     f"[{s['albedo_min']:.3f}, {s['albedo_max']:.3f}]")
    config.LOG.param("粗糙度", f"{s['roughness_mean']:.3f}")
    config.LOG.param("高光均值", f"{s['specular_mean']:.3f}")
    config.LOG.param("高度范围", f"{s['height_range']:.3f}")
    config.LOG.param("水面比例", f"{s['water_ratio']*100:.2f}%")

    return m


# ═══════════════════════════════════════════════════════════════════
# 通道 1：Albedo
# ═══════════════════════════════════════════════════════════════════
def _extract_albedo(R_clean: np.ndarray, cfg: dict) -> np.ndarray:
    """
    彩色先验法：

    物理：
      I = albedo × shading
      shading 是"灰"的（对 RGB 等比例影响）
      albedo 有色偏（不同通道不同反射率）

    步骤：
      1. 通道最小值 → shading 近似（假设光照使最暗通道不为 0）
      2. 平滑 shading → 消除纹理
      3. albedo = I / shading
      4. 归一化到 mean ≈ 1

    R_clean 已经是 Retinex 输出的反射率（均值匹配），
    这里再精修一次，把色偏从 shading 中分离。
    """
    H, W = R_clean.shape[:2]

    # 1. 通道最小值 → shading 灰度估计
    shading_est = R_clean.min(axis=2)  # (H, W)

    # 2. 平滑 shading（大半径高斯，只保留低频）
    blur_radius = max(4.0, min(W, H) * 0.03)
    shading_est = utils.blur_2d(shading_est, blur_radius)
    shading_est = np.maximum(shading_est, 1e-6)

    # 3. albedo = I / shading
    albedo = R_clean / shading_est[..., None]

    # 4. 归一化到 mean ≈ 1（保色偏但不改变亮度）
    m = float(albedo.mean())
    if m > 1e-6:
        albedo = albedo / m

    # 5. 限幅（防止极端值）
    albedo = np.clip(albedo, 0.05, 3.0)

    return albedo


# ═══════════════════════════════════════════════════════════════════
# 通道 2：Roughness
# ═══════════════════════════════════════════════════════════════════
def _extract_roughness(albedo: np.ndarray, cfg: dict) -> np.ndarray:
    """
    局部方差法：

    物理：
      光滑面 → 局部亮度方差小
      粗糙面 → 局部亮度方差大

    公式：
      σ_local = sqrt(E[I²] - E[I]²)
      roughness = clip(σ_local / mean, 0.1, 0.9)
    """
    H, W = albedo.shape[:2]
    lum = albedo.mean(axis=2)

    radius = max(3.0, min(W, H) * 0.008)

    # 局部均值 E[I]
    local_mean = utils.blur_2d(lum, radius)
    # 局部平方均值 E[I²]
    local_sq = utils.blur_2d(lum * lum, radius)

    # 方差
    local_var = np.maximum(local_sq - local_mean * local_mean, 0.0)
    local_std = np.sqrt(local_var)

    # 归一化
    denom = np.maximum(local_mean, 1e-4)
    roughness = local_std / denom * 2.0   # ×2 让对比更强

    # 限幅
    roughness = np.clip(roughness, 0.10, 0.90)

    return roughness


# ═══════════════════════════════════════════════════════════════════
# 通道 3：Normal
# ═══════════════════════════════════════════════════════════════════
def _extract_normal(albedo: np.ndarray, cfg: dict) -> np.ndarray:
    """
    亮度梯度法（Photometric Stereo 单光源近似）：

    物理：
      albedo 亮 → 凸起 → 法线远离墙面
      albedo 暗 → 凹陷 → 法线远离墙面
      梯度方向 = 从暗到亮

    公式：
      gx = ∂lum/∂x
      gy = ∂lum/∂y
      N = normalize(-gx, -gy, 1)

    注意：
      单张图无法唯一确定法线（法线歧义）
      作为视觉增强够用
    """
    H, W = albedo.shape[:2]
    lum = albedo.mean(axis=2)

    # 平滑掉高频噪声（保留几何起伏）
    radius = max(1.5, min(W, H) * 0.003)
    lum_smooth = utils.blur_2d(lum, radius)

    # Sobel 梯度（cv2 优先）
    gx, gy = _sobel_2d(lum_smooth)

    # 强度缩放（让梯度落在合理范围）
    # 亮度差 0.3 → 梯度 0.3/pixel → 法线倾斜 ~17°
    scale = float(cfg.get("normal_strength", 1.0))
    gx = gx * scale
    gy = gy * scale

    # 法线：N = (-gx, -gy, 1) 归一化
    # 亮度增加方向指向凸起中心 → 法线指向凸起
    normal = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    norm = np.linalg.norm(normal, axis=-1, keepdims=True)
    normal = normal / np.maximum(norm, 1e-6)

    return normal


def _sobel_2d(arr: np.ndarray):
    """返回 (gx, gy) 梯度。cv2 优先。"""
    if utils._HAS_CV2:
        # 转 uint8 会丢精度，用 float32 直接算
        gx = utils.cv2.Sobel(arr, utils.cv2.CV_32F, 1, 0, ksize=3)
        gy = utils.cv2.Sobel(arr, utils.cv2.CV_32F, 0, 1, ksize=3)
        # Sobel ksize=3 的归一化系数：1/4（核和=4）
        gx = gx / 4.0
        gy = gy / 4.0
        return gx, gy

    # numpy 回退
    gx = np.zeros_like(arr)
    gy = np.zeros_like(arr)
    # 中心差分
    gx[:, 1:-1] = (arr[:, 2:] - arr[:, :-2]) / 2.0
    gy[1:-1, :] = (arr[2:, :] - arr[:-2, :]) / 2.0
    return gx, gy


# ═══════════════════════════════════════════════════════════════════
# 通道 4：Specular
# ═══════════════════════════════════════════════════════════════════
def _extract_specular(albedo: np.ndarray, cfg: dict) -> np.ndarray:
    """
    局部高光法：

    物理：
      镜面高光 = 局部亮度超出周围"环境"的部分
      环境亮度 = 大半径高斯平滑

    公式：
      local_avg = blur(lum, σ_large)
      specular = max(0, lum - local_avg)
      归一化到 [0, 1]
    """
    H, W = albedo.shape[:2]
    lum = albedo.mean(axis=2)

    # 大半径平滑 → 局部环境亮度
    radius = max(8.0, min(W, H) * 0.05)
    local_avg = utils.blur_2d(lum, radius)

    # 超出部分
    specular = np.clip(lum - local_avg, 0.0, 1.0)

    # 归一化（让峰值到 1.0）
    peak = float(specular.max())
    if peak > 1e-6:
        specular = specular / peak

    return specular


# ═══════════════════════════════════════════════════════════════════
# 通道 5：Height
# ═══════════════════════════════════════════════════════════════════
def _extract_height(normal: np.ndarray, albedo: np.ndarray,
                    cfg: dict) -> np.ndarray:
    """
    法线积分法（近似）：

    物理：
      ∂h/∂x = -N_x / N_z
      ∂h/∂y = -N_y / N_z

    步骤：
      1. 从法线求偏导数
      2. 沿 x/y 积分（累积求和）
      3. 零均值化

    限制：
      单张图积分误差累积，仅用于视觉判断
    """
    H, W = albedo.shape[:2]

    nx = normal[..., 0]
    ny = normal[..., 1]
    nz = np.maximum(normal[..., 2], 1e-4)

    dhdx = -nx / nz
    dhdy = -ny / nz

    # 简单累加积分（center difference 已包含符号）
    h_x = np.cumsum(dhdx, axis=1)
    h_y = np.cumsum(dhdy, axis=0)

    # 组合（平均）
    height = (h_x + h_y) * 0.5

    # 零均值
    height = height - float(height.mean())

    # 限幅防止累积爆炸
    h_max = max(1e-6, float(np.abs(height).max()))
    height = height / h_max  # 归一化到 [-1, 1]

    return height


# ═══════════════════════════════════════════════════════════════════
# 水面判定
# ═══════════════════════════════════════════════════════════════════
def _detect_water(albedo: np.ndarray,
                  roughness: np.ndarray,
                  specular: np.ndarray,
                  cfg: dict) -> np.ndarray:
    """
    水面判定：

    物理特征：
      1. 低反射率（水透光，albedo 低）
      2. 低粗糙度（水面光滑）
      3. 局部高光强（太阳直射时）

    判定：
      is_water = (lum < 阈值) & (roughness < 阈值)
    """
    lum = albedo.mean(axis=2)

    lum_th = float(cfg.get("water_albedo_threshold", 0.10))
    rough_th = float(cfg.get("water_roughness_threshold", 0.20))

    is_water = (lum < lum_th) & (roughness < rough_th)

    # 形态学清理（cv2 优先）
    if utils._HAS_CV2:
        kernel = utils.cv2.getStructuringElement(utils.cv2.MORPH_ELLIPSE,
                                                  (5, 5))
        u8 = is_water.astype(np.uint8) * 255
        u8 = utils.cv2.morphologyEx(u8, utils.cv2.MORPH_OPEN, kernel)
        u8 = utils.cv2.morphologyEx(u8, utils.cv2.MORPH_CLOSE, kernel)
        is_water = u8 > 127

    return is_water.astype(bool)


# ═══════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════
def _self_test():
    """生成一个测试 R_clean，检查五通道。"""
    H, W = 128, 256
    rng = np.random.default_rng(42)

    # 模拟一个带裂纹和凸起的墙面
    base = 0.3 + 0.05 * rng.random((H, W, 3))
    # 加两条裂纹
    base[40:45, :, :] *= 0.5
    base[:, 100:105, :] *= 0.5
    # 加一块高光
    base[60:80, 180:200, :] += 0.4

    R_clean = base.astype(np.float32)

    m = extract_material(R_clean)
    s = m.stats()
    for k, v in s.items():
        print(f"  {k:20s} = {v:.4f}")
    print(f"  normal[0,0]         = {m.normal[0, 0]}")
    print(f"  is_water ratio      = {m.is_water.mean()*100:.2f}%")


if __name__ == "__main__":
    _self_test()