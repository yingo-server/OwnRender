#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光照子框架入口

只做 re-export。不包含任何业务逻辑。
"""
from .light import (
    compute_light,
    compute_scene_lights,
    LightResult,
    classify_light,
    classify_light_auto,
    describe_single_window_light,
    build_base_prompt,
    analyze_wall,
    diagnose_wall,
    predict_result,
)

from .scene3d import (
    Scene3D,
    sun_to_room_dir,
    default_scene,
)

from . import astro
from . import geometry
from . import scene
from . import raytrace
from . import utils

__all__ = [
    # 光照
    "compute_light",
    "compute_scene_lights",
    "LightResult",
    "classify_light",
    "classify_light_auto",
    "describe_single_window_light",
    "build_base_prompt",
    "analyze_wall",
    "diagnose_wall",
    "predict_result",
    # 3D 场景
    "Scene3D",
    "sun_to_room_dir",
    "default_scene",
    # 子模块
    "astro",
    "geometry",
    "scene",
    "raytrace",
    "utils",
]