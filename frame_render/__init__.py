#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染子框架入口

只做 re-export。不包含任何业务逻辑。
"""
from .pipeline import (
    generate_lit_wall,
    render_fusion,
)

from .utils import (
    srgb_to_linear,
    linear_to_srgb,
    aces_tonemap,
    aces_tonemap_with_gain,
    stable_seed,
    blur_2d,
    resize_np,
    report,
)

from . import utils
from . import retinex
from . import material
from . import compose
from . import text

__all__ = [
    # 主接口
    "generate_lit_wall",
    "render_fusion",
    # 工具
    "srgb_to_linear",
    "linear_to_srgb",
    "aces_tonemap",
    "aces_tonemap_with_gain",
    "stable_seed",
    "blur_2d",
    "resize_np",
    "report",
    # 子模块
    "utils",
    "retinex",
    "material",
    "compose",
    "text",
]