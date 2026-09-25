#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架入口

只做 re-export。不包含任何业务逻辑。
"""
from .runner import run, main_menu

__all__ = ["run", "main_menu"]