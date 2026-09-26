#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建模缓存：**同一个底图 + 同一套参数，绝不重复建模**。

设计（agent.md §8）
    缓存键 = sha256(底图字节)  ⊕  md5(几何/材质参数, 规范化 JSON)  ⊕  版本号
    缓存内容 = meta.json（房间/材质/开口等结构） + arrays.npz（材质图/掩膜/噪声）

    命中即跳过"泼溅/建模"（秒级 vs 分钟级），只有参数变了才重建。
    随机性一律由 seed 决定 → 缓存内容可复现。

本模块只写"键的算法 + 存取协议"；压缩/序列化交给 numpy（npz）与 json。
"""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

CACHE_VERSION = "v11"          # 结构一变就升版本，自动失效旧缓存


# ═══════════════════════════════════════════════════════════════════
# 缓存根目录
# ═══════════════════════════════════════════════════════════════════
def cache_root() -> Path:
    """缓存根目录。`OWNRENDER_HOME` 可覆盖（便携化）。"""
    env = os.environ.get("OWNRENDER_HOME")
    if env:
        return Path(env) / "models"
    try:
        base = Path.home() / ".cache" / "ownrender"
    except Exception:                                     # noqa: BLE001
        base = Path.cwd() / ".ownrender_cache"
    return base / "models"


# ═══════════════════════════════════════════════════════════════════
# 指纹与键
# ═══════════════════════════════════════════════════════════════════
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_params(params: dict) -> str:
    """参数指纹：**规范化 JSON**（键排序、浮点定长）→ md5。

    定长很重要：0.1 与 0.1000000000000001 必须视为同一参数（浮点噪声）。
    """
    def norm(x):
        if isinstance(x, float):
            return round(float(x), 6)
        if isinstance(x, (list, tuple)):
            return [norm(v) for v in x]
        if isinstance(x, dict):
            return {str(k): norm(v) for k, v in sorted(x.items())}
        return x

    blob = json.dumps(norm(params), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def model_key(image_fingerprint: str, params: dict,
              version: str = CACHE_VERSION) -> str:
    """完整缓存键：`<版本>-<sha8>-<md5_8>`（既定位唯一、又便于人眼核对）。"""
    return "%s-%s-%s" % (version, str(image_fingerprint)[:8], md5_params(params)[:8])


def model_path(key: str) -> Path:
    return cache_root() / key


# ═══════════════════════════════════════════════════════════════════
# 存取
# ═══════════════════════════════════════════════════════════════════
def exists(key: str) -> bool:
    p = model_path(key)
    return (p / "meta.json").is_file() and (p / "arrays.npz").is_file()


def save_model(key: str, meta: dict,
               arrays: Optional[Dict[str, np.ndarray]] = None) -> Path:
    """写入缓存（原子：先写临时目录再 rename，避免半成品被当成命中）。"""
    p = model_path(key)
    tmp = p.with_suffix(".tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    meta = dict(meta)
    meta.setdefault("_cache_version", CACHE_VERSION)
    meta.setdefault("_saved_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    (tmp / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    arrs = dict(arrays or {})
    if arrs:
        np.savez_compressed(tmp / "arrays.npz", **arrs)
    else:
        np.savez_compressed(tmp / "arrays.npz", _empty=np.zeros(0))

    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    tmp.rename(p)
    return p


def load_model(key: str) -> Optional[Tuple[dict, Dict[str, np.ndarray]]]:
    """读取缓存；不存在/损坏返回 None（调用方据此重建）。"""
    if not exists(key):
        return None
    try:
        meta = json.loads((model_path(key) / "meta.json").read_text(encoding="utf-8"))
        with np.load(model_path(key) / "arrays.npz") as z:
            arrays = {k: z[k] for k in z.files}
        return meta, arrays
    except Exception:                                     # noqa: BLE001
        return None


def purge(keep_last: int = 32) -> int:
    """清理旧缓存（按 mtime 保留最近 keep_last 个）。返回删除数量。"""
    root = cache_root()
    if not root.is_dir():
        return 0
    items = sorted((d for d in root.iterdir() if d.is_dir()),
                   key=lambda d: d.stat().st_mtime, reverse=True)
    n = 0
    for d in items[max(0, int(keep_last)):]:
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


# ═══════════════════════════════════════════════════════════════════
# 便捷入口：给"底图 + 参数"用
# ═══════════════════════════════════════════════════════════════════
def key_for_image(image_path, params: dict) -> str:
    return model_key(sha256_file(image_path), params)


def get_or_build(image_path, params: dict, builder):
    """命中返回 (meta, arrays, True)；未命中则调用 builder() 生成并落盘。

    builder() 约定返回 (meta, arrays)。
    """
    key = key_for_image(image_path, params)
    hit = load_model(key)
    if hit is not None:
        return hit[0], hit[1], True
    meta, arrays = builder()
    save_model(key, meta, arrays)
    return meta, arrays, False


# ═══════════════════════════════════════════════════════════════════
# 自检（python -m ownrender.scene3d.cache）
# ═══════════════════════════════════════════════════════════════════
def _self_test():                                            # pragma: no cover
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="ow-cache-"))
    img = tmp / "wall.png"
    img.write_bytes(b"\x89PNG fake bytes for key test" * 10)

    p1 = {"room": [4.0, 3.0, 4.0], "window": [1.2, 1.5], "seed": 20260926}
    p2 = dict(p1, seed=1)

    k1 = key_for_image(img, p1)
    k1b = key_for_image(img, p1)
    k2 = key_for_image(img, p2)
    print("键1 = %s（两次一致：%s）" % (k1, k1 == k1b))
    print("键2 = %s（参数不同 → 不同键：%s）" % (k2, k1 != k2))

    save_model(k1, {"room": p1["room"]}, {"albedo": np.zeros((4, 4, 3))})
    hit = load_model(k1)
    print("命中：", hit is not None, "| meta:", hit[0] if hit else None)
    print("未命中（另一参数）：", load_model(k2) is None)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()