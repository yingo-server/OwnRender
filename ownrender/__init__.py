#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OwnRender 重构后的包（见 agent.md）。

重构期间旧实现（frame_light / frame_render / frame_interact）保持可用，
新代码按 core → scene3d → light → transport → surface → textoverlay → pipeline
分层落地，逐阶段替换。
"""
__version__ = "11.0.0"
__all__ = ["__version__"]