#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数注册表的守门测试（agent.md §11）。

两条硬规则：
  R1 每个细分方面 ≥15 个参数
  R2 "风格手调"参数只能是白名单里的工程/数值项（审美旋钮永久禁止）
另外校验：键唯一、默认值在范围内、单位非空、kind 合法。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ownrender.core import params as PR       # noqa: E402


def test_every_aspect_has_15plus_params():
    counts = PR.aspect_counts()
    assert len(counts) >= 16, counts
    short = {k: v for k, v in counts.items() if v < 15}
    assert not short, "这些方面参数不足 15：%s" % short


def test_total_param_count():
    total = sum(PR.aspect_counts().values())
    assert total >= 240, "参数总数 %d 偏少" % total


def test_keys_unique_and_prefixed():
    seen = set()
    for aspect, lst in PR.ASPECTS.items():
        for p in lst:
            assert p.key not in seen, "键重复：%s" % p.key
            seen.add(p.key)
            assert p.key.startswith(aspect + "."), \
                "%s 的前缀应与方面 %s 一致" % (p.key, aspect)


def test_defaults_within_range():
    bad = [p.key for p in PR.all_params().values()
           if not (p.lo <= p.default <= p.hi)]
    assert not bad, "默认值越界：%s" % bad


def test_units_present():
    for p in PR.all_params().values():
        assert p.unit, "%s 缺单位" % p.key
        assert p.src, "%s 缺出处（src）" % p.key


def test_tunable_whitelist_only():
    """R2：tunable 只能来自白名单，且总数很少（工程/数值项）。"""
    tun = [k for k, p in PR.all_params().items() if p.kind == "tunable"]
    extra = [k for k in tun if k not in PR.TUNABLE_WHITELIST]
    assert not extra, "未列入白名单的 tunable：%s" % extra


def test_validate_clean():
    bad = PR.validate()
    assert not bad, bad


def test_no_style_table_remnants():
    """禁止出现"天气 → 亮度/对比度"的风格表（历史教训）。"""
    src = (Path(PR.__file__).parent.parent.parent / "ownrender"
           / "core" / "params.py").read_text(encoding="utf-8")
    for banned in ("WEATHER_LOOK", "style_table", "brightness_by_weather"):
        assert banned not in src, "参数注册表里不应出现 %s" % banned


def test_registry_matches_physics_modules():
    """★ 单一事实源必须闭环：注册表 ↔ 物理模块里的常数不许漂移。"""
    from frame_light import atmosphere as ATM

    pairs = [
        ("precip.film_ref_mm", ATM.WATER_FILM_REF_MM),
        ("cloud.optical_depth", ATM.TAU_CLOUD_THICK),
        ("color.eye_adapt_gamma", ATM.EYE_ADAPT_GAMMA),
        ("ground.albedo_snow", ATM.GROUND_ALBEDO["snow"]),
        ("ground.albedo_wet", ATM.GROUND_ALBEDO["wet"]),
        ("ground.albedo_dry", ATM.GROUND_ALBEDO["dry"]),
        ("transport.room_reflectance", ATM.GROUND_ALBEDO["room"]),
    ]
    for key, legacy in pairs:
        p = PR.get(key)
        assert p is not None, key
        assert abs(float(p.default) - float(legacy)) < 1e-9, \
            "%s 注册表=%g 与模块=%g 不一致" % (key, p.default, legacy)