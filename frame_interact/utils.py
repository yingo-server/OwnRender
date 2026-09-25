#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 工具

本文件专用。不 import 本框架其他文件。
包含：终端常量、TUI 原语（h/ok/ask/menu）、格式化

注意：
  为保证「完全独立」，本文件不 import 任何其他子框架。
  跨框架数据（如 astro 的天气）由 offline.py / ai.py 自己获取。
"""
import sys
import shutil

import config


# ═══════════════════════════════════════════════════════════════════
# 终端常量
# ═══════════════════════════════════════════════════════════════════
_TERM_COLS = 80
_IS_NARROW = False
_FIELD_W = 16
_BAR_W = 28


def init_term():
    global _TERM_COLS, _IS_NARROW, _FIELD_W, _BAR_W
    try:
        _TERM_COLS = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        _TERM_COLS = 80
    _IS_NARROW = _TERM_COLS < 60
    _FIELD_W = 12 if _IS_NARROW else 16
    _BAR_W = max(10, min(28, _TERM_COLS - 40))


# ═══════════════════════════════════════════════════════════════════
# TUI 原语
# ═══════════════════════════════════════════════════════════════════
def h(t):    print(f"\n==> {t}")
def ok(m):   print(f"  + {m}")
def err(m):  print(f"  - {m}", file=sys.stderr)
def warn(m): print(f"  ! {m}")
def info(m): print(f"  * {m}")


def field(k, v, w=None):
    w = w or _FIELD_W
    s = str(v)
    mx = _TERM_COLS - w - 6
    if mx > 8 and len(s) > mx:
        s = s[:mx - 1] + "…"
    print(f"    {k.ljust(w)} {s}")


def trunc(s, n=40):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def ask(label, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        v = input(f"  ? {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    return v if v else (default or "")


def ask_multiline(label, default=""):
    print(f"  ? {label}")
    print(f"    (空行结束，回车保留原值)")
    if default:
        print(f"    当前: {trunc(default, 60)}")
    lines = []
    while True:
        try:
            line = input("      > ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines) if lines else default


def ask_yn(label, default="y"):
    while True:
        raw = ask(f"{label} (y/n)", default).strip().lower()
        if raw in ("y", "yes", ""):
            return True
        if raw in ("n", "no"):
            return False
        warn("请输入 y 或 n")


def menu(title, options, default=0):
    print(f"\n  {title}")
    for i, opt in enumerate(options):
        mark = ">" if i == default else " "
        mx = _TERM_COLS - 8
        text = opt if len(opt) <= mx else opt[:mx - 1] + "…"
        print(f"    {mark} [{i}] {text}")
    try:
        idx = int(ask("选择", str(default)))
    except ValueError:
        return default
    return idx if 0 <= idx < len(options) else default


# ═══════════════════════════════════════════════════════════════════
# 数字输入（带范围检查）
# ═══════════════════════════════════════════════════════════════════
def ask_float_range(label, lo, hi, default, ndigits=4):
    """询问一个 float，超出范围返回 None。"""
    try:
        v = float(ask(f"{label} [{lo}~{hi}]", str(default)))
    except (ValueError, TypeError):
        warn("无效数值")
        return None
    if not (lo <= v <= hi):
        warn(f"超出范围 [{lo}, {hi}]")
        return None
    return round(v, ndigits)


def ask_int_range(label, lo, hi, default):
    try:
        v = int(ask(f"{label} [{lo}~{hi}]", str(default)))
    except (ValueError, TypeError):
        warn("无效整数")
        return None
    if not (lo <= v <= hi):
        warn(f"超出范围 [{lo}, {hi}]")
        return None
    return v


def ask_rgb(label, default):
    """询问 RGB 三元组。返回 list 或 None。"""
    s = ask(f"{label} (R,G,B)", ",".join(str(x) for x in default))
    try:
        parts = [float(x.strip()) for x in s.split(",")]
        if len(parts) != 3:
            warn("需要 3 个数")
            return None
        return [round(p, 4) for p in parts]
    except (ValueError, TypeError):
        warn("格式错误")
        return None