#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — 进度条三件套

ProgressBar  — 单阶段文件写入进度条
Spinner      — API 请求旋转指示器
GlobalProgress — 多阶段全局进度条（0.01% 精度，50Hz 刷新）

只 import utils（本框架）+ 标准库。
"""
import sys
import time
from typing import List, Optional

from . import utils


_BAR_W = 28


def _get_bar_w():
    return max(10, min(28, utils._TERM_COLS - 40))


# ═══════════════════════════════════════════════════════════════════
class ProgressBar:
    """单阶段文件写入进度条。"""

    def __init__(self, total, label="", width=None, show_count=None):
        self.total = max(1, int(total))
        self.current = 0
        self.label = label
        self.width = width or _get_bar_w()
        self.show_count = (show_count if show_count is not None
                           else (not utils._IS_NARROW))
        self._last = 0.0

    def _render(self, force=False):
        now = time.time()
        if not force and (now - self._last) < 0.02:
            return
        self._last = now
        r = min(1.0, self.current / self.total)
        f = int(self.width * r)
        bar = "=" * self.width if f >= self.width else \
              "=" * f + ">" + "-" * (self.width - f - 1)
        parts = []
        if self.label and not utils._IS_NARROW:
            parts.append(self.label)
        parts.append(f"[{bar}]")
        parts.append(f"{r * 100:6.2f}%")
        if self.show_count:
            parts.append(f"{self.current}/{self.total}")
        try:
            sys.stdout.write("\r  " + " ".join(parts))
            sys.stdout.flush()
        except (OSError, UnicodeEncodeError):
            pass

    def update(self, n=1):
        self.current = min(self.current + n, self.total)
        self._render()

    def finish(self):
        self.current = self.total
        self._render(force=True)
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except (OSError, UnicodeEncodeError):
            pass

    def __enter__(self):
        self._render(force=True)
        return self

    def __exit__(self, *a):
        self.finish()


# ═══════════════════════════════════════════════════════════════════
class Spinner:
    """API 请求旋转指示器。"""
    CHARS = ["|", "/", "-", "\\"]

    def __init__(self, label=""):
        self.label = label
        self.idx = 0
        self._start = time.time()
        self._running = False

    def tick(self):
        self._running = True
        ch = self.CHARS[self.idx % 4]
        self.idx += 1
        try:
            if utils._IS_NARROW:
                sys.stdout.write(f"\r  {ch} {time.time() - self._start:5.1f}s")
            else:
                sys.stdout.write(
                    f"\r  {self.label} {ch}  ({time.time() - self._start:5.1f}s)")
            sys.stdout.flush()
        except (OSError, UnicodeEncodeError):
            pass

    def stop(self, msg=None):
        if self._running:
            try:
                if msg and not utils._IS_NARROW:
                    sys.stdout.write(
                        f"\r  {msg}  ({time.time()-self._start:5.1f}s)   \n")
                else:
                    sys.stdout.write("\r" + " " * utils._TERM_COLS + "\r")
                sys.stdout.flush()
            except (OSError, UnicodeEncodeError):
                pass
            self._running = False


# ═══════════════════════════════════════════════════════════════════
class GlobalProgress:
    """多阶段全局进度条（0.01% 精度，50Hz 刷新）。"""

    def __init__(self, enabled=True):
        self.enabled = enabled and not utils._IS_NARROW
        self.stages: List[str] = []
        self.current_stage = -1
        self.stage_progress = 0.0
        self._last = 0.0
        self._line_started = False

    def set_stages(self, stages: List[str]):
        self.stages = list(stages)
        self.current_stage = -1
        self.stage_progress = 0.0

    def set_stage(self, idx: int, name: str = ""):
        self.current_stage = idx
        self.stage_progress = 0.0
        if name:
            while len(self.stages) <= idx:
                self.stages.append(f"阶段{len(self.stages)}")
            self.stages[idx] = name
        self._render(force=True)

    def set_progress(self, p: float):
        self.stage_progress = max(0.0, min(1.0, round(float(p), 4)))
        self._render()

    def _render(self, force=False):
        if not self.enabled:
            return
        now = time.time()
        if not force and (now - self._last) < 0.02:
            return
        self._last = now
        total = max(1, len(self.stages))
        done = max(0, self.current_stage)
        g = (done + self.stage_progress) / total
        bar_w = _get_bar_w()
        f = int(bar_w * g)
        bar = "=" * bar_w if f >= bar_w else \
              "=" * f + ">" + "-" * (bar_w - f - 1)
        name = (self.stages[self.current_stage]
                if 0 <= self.current_stage < len(self.stages) else "…")
        if len(name) > 22:
            name = name[:21] + "…"
        try:
            sys.stdout.write(f"\r  [{bar}] {g*100:6.2f}% {name:<22}")
            sys.stdout.flush()
            self._line_started = True
        except (OSError, UnicodeEncodeError):
            pass

    def log(self, msg):
        if self.enabled and self._line_started:
            try:
                sys.stdout.write("\r" + " " * utils._TERM_COLS + "\r")
            except (OSError, UnicodeEncodeError):
                pass
        print(f"  * {msg}")
        if self.enabled:
            self._render(force=True)

    def finish(self):
        if not self.enabled:
            self._line_started = False
            return
        self.current_stage = len(self.stages)
        self.stage_progress = 0.0
        self._render(force=True)
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except (OSError, UnicodeEncodeError):
            pass
        self._line_started = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.finish()