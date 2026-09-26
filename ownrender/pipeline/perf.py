#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能计时与预算守门（agent.md §17）。

用户硬指标：
    · 冷启动 → 首图 **≤ 90 s**
    · 连续构建 **≤ 10 s / 张**

本模块只做两件事：
    1. 给各阶段计时（导入 / 缓存命中 / 场景构建 / 编码 / 渲染）
    2. 用注册表里的预算**守门**：先证明"我们的代码不吃掉预算"，
       剩下的才归后端（Blender/自研光追）。

用法：
    python -m ownrender.pipeline.perf            # 跑一次本地基准
"""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ownrender.core import params as PR       # noqa: E402

STAGES: List[str] = []


# ═══════════════════════════════════════════════════════════════════
# 计时
# ═══════════════════════════════════════════════════════════════════
@contextmanager
def stage(name: str, budget_ms: Optional[float] = None,
          sink: Optional[Dict[str, float]] = None):
    """计时上下文；给了 budget_ms 就当场守门（超了抛 BudgetError）。"""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if sink is not None:
            sink[name] = dt_ms
        STAGES.append("%s=%.1fms" % (name, dt_ms))
        if budget_ms is not None and dt_ms > budget_ms:
            raise BudgetError("阶段 %s 超预算：%.1fms > %.1fms"
                              % (name, dt_ms, budget_ms))


class BudgetError(RuntimeError):
    pass


def budget(key: str) -> float:
    """取预算（注册表为准）。"""
    p = PR.get(key)
    if p is None:
        raise KeyError("没有这个预算参数：%s" % key)
    return float(p.default)


# ═══════════════════════════════════════════════════════════════════
# 本地基准（可被 CI/本机运行）
# ═══════════════════════════════════════════════════════════════════
def bench(verbose: bool = True) -> Dict[str, float]:
    """量"我们这段"的耗时：必须远小于 90s / 10s 预算。"""
    out: Dict[str, float] = {}

    t0 = time.perf_counter()
    from ownrender.core import params as _p          # noqa: F401
    from ownrender.scene3d import cache as _c        # noqa: F401
    from ownrender.scene3d.room import Room as _R    # noqa: F401
    from ownrender.render3d.scene import SceneSpec as _S   # noqa: F401
    from ownrender.render3d import blender as _B     # noqa: F401
    out["import_ms"] = (time.perf_counter() - t0) * 1000.0

    # 1) 场景构建（参数化路径：房间 → SceneSpec → bpy 脚本）
    t0 = time.perf_counter()
    from ownrender.scene3d.room import Room
    from ownrender.render3d.scene import SceneSpec
    from ownrender.render3d.blender import build_script
    room = Room(4.0, 3.0, 4.0)
    room.add_window("right", 0.0, 0.0, 1.2, 1.5)
    spec = SceneSpec.from_room(room)
    src = build_script(spec, "/tmp/ow_bench.png")
    out["scene_build_ms"] = (time.perf_counter() - t0) * 1000.0
    out["script_lines"] = float(len(src.splitlines()))

    # 2) 缓存命中路径（写一次 + 命中读一次）
    import tempfile
    from ownrender.scene3d import cache
    old_home = os.environ.get("OWNRENDER_HOME")
    tmp = tempfile.mkdtemp(prefix="ow-perf-")
    os.environ["OWNRENDER_HOME"] = tmp
    try:
        img = Path(tmp) / "wall.png"
        img.write_bytes(b"perf-test-image" * 200)
        key = cache.key_for_image(img, {"room": [4.0, 3.0, 4.0], "seed": 1})
        cache.save_model(key, {"ok": True}, {"a": __import__("numpy").zeros((64, 64, 3))})
        t0 = time.perf_counter()
        for _ in range(20):
            cache.load_model(key)
        out["cache_hit_ms"] = (time.perf_counter() - t0) * 1000.0 / 20.0
    finally:
        if old_home is None:
            os.environ.pop("OWNRENDER_HOME", None)
        else:
            os.environ["OWNRENDER_HOME"] = old_home

    # 3) 参数表读取（每次渲染都要读）
    t0 = time.perf_counter()
    PR.all_params()
    out["params_ms"] = (time.perf_counter() - t0) * 1000.0

    if verbose:
        print("—— 本地基准（我们的代码）——")
        for k in sorted(out):
            print("  %-16s %8.2f" % (k, out[k]))
        print("—— 预算对照 ——")
        print("  导入      预算 %.0fms  实际 %.0fms" %
              (budget("perf.import_budget_ms"), out["import_ms"]))
        print("  场景构建  预算 %.0fms  实际 %.0fms" %
              (budget("perf.scene_build_budget_ms"), out["scene_build_ms"]))
        print("  缓存命中  预算 %.0fms  实际 %.0fms" %
              (budget("perf.cache_hit_budget_ms"), out["cache_hit_ms"]))
        print("  单张预算 %.0fs（我们的部分占 %.0fms，其余归后端渲染）" %
              (budget("perf.per_photo_budget_s"), out["scene_build_ms"]))
    return out


def _self_test():                                            # pragma: no cover
    out = bench(verbose=True)
    bad = []
    if out["import_ms"] > budget("perf.import_budget_ms"):
        bad.append("import_ms")
    if out["scene_build_ms"] > budget("perf.scene_build_budget_ms"):
        bad.append("scene_build_ms")
    if out["cache_hit_ms"] > budget("perf.cache_hit_budget_ms"):
        bad.append("cache_hit_ms")
    print("预算守门：", "全部通过 ✅" if not bad else "❌ %s" % bad)


if __name__ == "__main__":                                   # pragma: no cover
    _self_test()