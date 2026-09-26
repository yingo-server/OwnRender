#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缓存键与存取的守门测试（"不重复泼溅房间"的保证）。"""
import tempfile
import time
from pathlib import Path

import numpy as np

from ownrender.scene3d import cache


def test_key_deterministic():
    p = {"room": [4.0, 3.0, 4.0], "seed": 20260926, "window": [1.2, 1.5]}
    assert cache.md5_params(p) == cache.md5_params(dict(p))
    assert cache.model_key("abcdef1234", p) == cache.model_key("abcdef1234", p)


def test_key_sensitive_to_params_and_image():
    p = {"room": [4.0, 3.0, 4.0], "seed": 1}
    k1 = cache.model_key("abcdef1234", p)
    k2 = cache.model_key("abcdef1234", dict(p, seed=2))
    k3 = cache.model_key("ffffffff99", p)
    assert k1 != k2 and k1 != k3


def test_float_noise_ignored():
    """浮点噪声（1e-12）不应导致重建缓存。"""
    a = cache.md5_params({"x": 0.1})
    b = cache.md5_params({"x": 0.1 + 1e-12})
    assert a == b


def test_save_load_roundtrip(tmp_ok=None):
    """注意：缓存键是**内容哈希**，所以测试必须自封闭（临时 OWNRENDER_HOME），
    否则上一轮跑出来的缓存会让"第一次也命中"，测试就不 hermetic 了。"""
    import os
    old_home = os.environ.get("OWNRENDER_HOME")
    tmp_home = Path(tempfile.mkdtemp(prefix="ow-home-"))
    os.environ["OWNRENDER_HOME"] = str(tmp_home)
    try:
        tmp = Path(tempfile.mkdtemp(prefix="ow-cache-test-"))
        img = tmp / "wall.png"
        img.write_bytes(b"fake-png" * 100)
        params = {"room": [4, 3, 4], "seed": 7}

        called = {"n": 0}

        def builder():
            called["n"] += 1
            return ({"info": "built"}, {"albedo": np.full((3, 3, 3), 0.5)})

        meta, arrs, hit1 = cache.get_or_build(img, params, builder)
        assert hit1 is False and called["n"] == 1
        meta2, arrs2, hit2 = cache.get_or_build(img, params, builder)
        assert hit2 is True and called["n"] == 1, "第二次必须命中缓存，不得重建"
        assert np.allclose(arrs2["albedo"], arrs["albedo"])

        # 参数一变 → 未命中 → 重建
        meta3, _, hit3 = cache.get_or_build(img, dict(params, seed=8), builder)
        assert hit3 is False and called["n"] == 2
    finally:
        if old_home is None:
            os.environ.pop("OWNRENDER_HOME", None)
        else:
            os.environ["OWNRENDER_HOME"] = old_home


def test_load_missing_returns_none():
    assert cache.load_model("v11-deadbeef-cafebabe") is None


def test_sha256_file_stable():
    tmp = Path(tempfile.mkdtemp(prefix="ow-cache-test2-"))
    f = tmp / "a.bin"
    f.write_bytes(b"hello world")
    assert cache.sha256_file(f) == cache.sha256_file(f)
    assert cache.sha256_file(f) != cache.sha256_bytes(b"hello worlD")