#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互子框架 — TUI 工具箱（重建版）

只提供「渲染 + 交互」原语，不含任何业务逻辑：
  - 颜色（非 TTY / NO_COLOR 自动降级）
  - 标题 / 分节 / 状态行 / 面板
  - 编号菜单（默认项高亮、支持返回）
  - 输入原语（文本/整数/浮点/布尔/单选/多行/RGB）
  - Wizard：步骤总览 + 任意跳转编辑

本文件不 import 本框架其他文件，只 import config + 标准库。
"""
import os
import shutil
import sys

import config

# ═══════════════════════════════════════════════════════════════════
# 终端
# ═══════════════════════════════════════════════════════════════════
_COLS = 80
_NARROW = False
_WIDE = False


def init_term():
    global _COLS, _NARROW, _WIDE
    try:
        _COLS = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        _COLS = 80
    _NARROW = _COLS < 64
    _WIDE = _COLS >= 96


def cols():
    return _COLS


def _supports_color():
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


_COLOR = _supports_color()


def init_color(force=None):
    global _COLOR
    if force is not None:
        _COLOR = bool(force)
    else:
        _COLOR = _supports_color()


def paint(s, code):
    return f"\033[{code}m{s}\033[0m" if _COLOR else str(s)


def bold(s):    return paint(s, "1")
def dim(s):     return paint(s, "2")
def red(s):     return paint(s, "31")
def green(s):   return paint(s, "32")
def yellow(s):  return paint(s, "33")
def blue(s):    return paint(s, "34")
def magenta(s): return paint(s, "35")
def cyan(s):    return paint(s, "36")
def grey(s):    return paint(s, "90")


def _char_w(ch):
    """东亚宽字符按 2 列计。"""
    o = ord(ch)
    return 2 if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
                 or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                 or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
                 or 0xFFE0 <= o <= 0xFFE6 or o >= 0x20000) else 1


def _vis_len(s):
    """去掉 ANSI 后的可见宽度（列数）。"""
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j < 0:
                break
            i = j + 1
        else:
            out += _char_w(s[i])
            i += 1
    return out


def _pad(s, n):
    return s + " " * max(0, n - _vis_len(s))


# ═══════════════════════════════════════════════════════════════════
# 结构
# ═══════════════════════════════════════════════════════════════════
def blank():
    print()


def rule(ch="─", width=None):
    w = width or min(_COLS, 76)
    print(grey(ch * w))


def title(t, subtitle=None):
    blank()
    print(bold(cyan("◆ " + str(t))))
    if subtitle:
        print(dim("  " + str(subtitle)))
    rule()


def section(t):
    blank()
    print(bold("▸ " + str(t)))


def ok(m):    print(green("  ✓ ") + str(m))
def warn(m):  print(yellow("  ! ") + str(m))
def err(m):   print(red("  ✗ ") + str(m), file=sys.stderr)
def info(m):  print(cyan("  · ") + str(m))
def raw(m):   print("  " + str(m))


def field(k, v, w=None):
    w = w or (12 if _NARROW else 18)
    s = str(v)
    mx = _COLS - w - 8
    if mx > 8 and _vis_len(s) > mx:
        s = s[:mx - 1] + "…"
    print(f"    {grey(_pad(k, w))} {s}")


def panel(title_text, rows, note=None):
    """带框面板：rows 为 (key, value) 列表。"""
    width = min(_COLS, 76)
    tl = _vis_len(str(title_text))
    print()
    print(grey("┌─ ") + bold(str(title_text)) + " "
          + grey("─" * max(0, width - tl - 5) + "┐"))
    kw = max((_vis_len(str(k)) for k, _ in rows), default=0)
    kw = min(kw, 22)
    for k, v in rows:
        s = str(v)
        mx = width - kw - 8
        if mx > 8 and _vis_len(s) > mx:
            s = s[:mx - 1] + "…"
        print(grey("│ ") + grey(_pad(str(k), kw)) + "  " + s)
    print(grey("└" + "─" * (width - 2) + "┘"))
    if note:
        print(dim("  " + str(note)))


def trunc(s, n=48):
    s = str(s).replace("\n", " ")
    return s if _vis_len(s) <= n else s[:n - 1] + "…"


# ═══════════════════════════════════════════════════════════════════
# 中断
# ═══════════════════════════════════════════════════════════════════
class Abort(Exception):
    """用户中断（Ctrl-C / EOF）。"""


def _read(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise Abort()


def hint_key(label, hint):
    print(grey(f"    {label}") + (dim(f"  ({hint})") if hint else ""))


# ═══════════════════════════════════════════════════════════════════
# 菜单
# ═══════════════════════════════════════════════════════════════════
def menu(title_text, options, default=0, hint=None, back=None,
         keys=None, notes=None):
    """
    编号菜单。返回所选索引；输入 q 且给了 back 时返回 back。
    options: 字符串列表；notes: 与 options 等长的灰色注解（可选）。
    """
    blank()
    print(bold("  " + str(title_text)))
    for i, opt in enumerate(options):
        mark = cyan("▸") if i == default else " "
        num = bold(f"[{i}]") if i == default else grey(f"[{i}]")
        line = f"   {mark} {num} {opt}"
        note = notes[i] if notes and i < len(notes) else None
        if note:
            line += dim(f"   {note}")
        mx = _COLS - 2
        print(_clip(line, mx))
    tail = []
    if hint:
        tail.append(hint)
    tail.append(f"回车={default}")
    if back is not None:
        tail.append("q=返回")
    print(grey("     " + "  ".join(tail)))
    while True:
        s = _read(grey("  选择 > ")).strip().lower()
        if s == "":
            return default
        if back is not None and s in ("q", "quit", "back", "返回"):
            return back
        if keys:
            for k, idx in keys.items():
                if s == k:
                    return idx
        try:
            v = int(s)
        except ValueError:
            warn("请输入编号")
            continue
        if 0 <= v < len(options):
            return v
        warn(f"编号范围 0~{len(options) - 1}")


def _clip(s, mx):
    """按可见长度裁剪整行（含 ANSI）。"""
    if _vis_len(s) <= mx:
        return s
    out, vis, i = [], 0, 0
    while i < len(s) and vis < mx - 1:
        if s[i] == "\033":
            j = s.find("m", i)
            if j < 0:
                break
            out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(s[i])
            vis += 1
            i += 1
    out.append("…")
    if _COLOR:
        out.append("\033[0m")
    return "".join(out)


# ═══════════════════════════════════════════════════════════════════
# 输入原语
# ═══════════════════════════════════════════════════════════════════
def ask(label, default=None, allow_empty=False, secret=False):
    suffix = dim(f" [{default}]") if default not in (None, "") else ""
    while True:
        s = _read(f"   {grey(label)}{suffix}: ").strip()
        if s:
            return s
        if default not in (None, ""):
            return str(default)
        if allow_empty:
            return ""
        warn("不能为空")


def ask_int(label, lo, hi, default):
    while True:
        s = ask(f"{label} [{lo}~{hi}]", default)
        try:
            v = int(float(s))
        except ValueError:
            warn("需要整数")
            continue
        if lo <= v <= hi:
            return v
        warn(f"超出范围 {lo}~{hi}")


def ask_float(label, lo, hi, default, ndigits=4):
    while True:
        s = ask(f"{label} [{lo}~{hi}]", default)
        try:
            v = float(s)
        except ValueError:
            warn("需要数值")
            continue
        if lo <= v <= hi:
            return round(v, ndigits)
        warn(f"超出范围 {lo}~{hi}")


def ask_bool(label, default=True):
    d = "y" if default else "n"
    while True:
        s = ask(f"{label} (y/n)", d).strip().lower()
        if s in ("y", "yes", "1", "是"):
            return True
        if s in ("n", "no", "0", "否"):
            return False
        warn("请输入 y 或 n")


def ask_choice(label, options, default=0, notes=None):
    return menu(label, options, default=default, notes=notes)


def ask_rgb(label, default):
    while True:
        s = ask(label + " R,G,B (0~1)", ",".join(f"{x:g}" for x in default))
        try:
            p = [float(x.strip()) for x in s.split(",")]
        except ValueError:
            warn("格式错误")
            continue
        if len(p) != 3:
            warn("需要 3 个数")
            continue
        if all(0.0 <= x <= 1.0 for x in p):
            return [round(x, 4) for x in p]
        warn("范围 0~1")


def ask_text_block(label, default=""):
    print()
    print(bold(f"  {label}"))
    print(grey("  空行结束；直接回车保留原值"))
    if default:
        print(grey(f"  当前: {trunc(default, 64)}"))
    lines = []
    while True:
        s = _read(grey("    > "))
        if s == "":
            break
        lines.append(s)
    if not lines:
        return default
    return "\n".join(lines) if default and "\n" in default else "".join(lines)


def pause(msg="回车继续"):
    try:
        _read(grey(f"  {msg} …"))
    except Abort:
        pass


# ═══════════════════════════════════════════════════════════════════
# Wizard：步骤总览 + 任意跳转
# ═══════════════════════════════════════════════════════════════════
class Step:
    def __init__(self, key, label, edit, summary=None, optional=False):
        self.key = key
        self.label = label
        self.edit = edit          # edit() -> None，直接改 plan
        self.summary = summary    # summary() -> str
        self.optional = optional


class Wizard:
    """参数向导：一次性列出全部步骤，可反复跳转修改，最后确认。"""

    def __init__(self, plan, steps, title_text="参数向导",
                 confirm_label="开始生成"):
        self.plan = plan
        self.steps = steps
        self.title = title_text
        self.confirm_label = confirm_label

    # ── 总览 ──
    def _overview(self):
        blank()
        print(bold(cyan(f"  {self.title}")))
        rule()
        for i, st in enumerate(self.steps):
            try:
                s = st.summary() if st.summary else ""
            except Exception:
                s = ""
            num = grey(f"[{i}]")
            print(f"   {num} {_pad(st.label, 10)} " + (dim(trunc(s, 60)) if s else ""))
        rule()

    def run(self) -> bool:
        """返回 True=确认生成，False=放弃。"""
        while True:
            self._overview()
            n = len(self.steps)
            c = menu(
                "选择要修改的步骤（回车=确认）",
                [s.label for s in self.steps] + [green(self.confirm_label),
                                                 red("放弃")],
                default=n,
            )
            if c == n:
                return True
            if c == n + 1:
                return False
            try:
                self.steps[c].edit()
            except Abort:
                print()
                info("已取消该步编辑")


# ═══════════════════════════════════════════════════════════════════
# 通用映射编辑器（给设置页用：任意 dict 全字段可改）
# ═══════════════════════════════════════════════════════════════════
def edit_mapping(title_text, data, save_fn, skip_prefixes=("_",),
                 label_map=None, note=None):
    """
    把 dict 的所有叶子字段列出来，逐个可改。bool→y/n，number→数值，
    list[str]→文本，其余→字符串。
    返回 (changed: bool, data)。
    """
    label_map = label_map or {}
    while True:
        keys = [k for k in data.keys()
                if not any(k.startswith(p) for p in skip_prefixes)]
        blank()
        print(bold(cyan(f"  {title_text}")))
        rule()
        for i, k in enumerate(keys):
            v = data[k]
            if isinstance(v, dict):
                s = dim("（子分组，%d 项）" % len(v))
            else:
                s = str(v)
            print(f"   {grey('[' + str(i) + ']')} {_pad(label_map.get(k, k), 26)} "
                  + trunc(s, 30))
        rule()
        if note:
            print(dim("  " + note))
        c = menu("选择要修改的项", ["（改完返回）"] + keys, default=0)
        if c == 0:
            return data
        k = keys[c - 1]
        v = data[k]
        print()
        print(bold(f"  {label_map.get(k, k)}") + dim(f"   当前: {v}"))
        if isinstance(v, dict):
            edit_mapping(f"{title_text} / {label_map.get(k, k)}", v, lambda d: None)
            continue
        if isinstance(v, bool):
            data[k] = ask_bool("新值", v)
        elif isinstance(v, int):
            data[k] = ask_int("新值", -10 ** 9, 10 ** 9, v)
        elif isinstance(v, float):
            data[k] = ask_float("新值", -10 ** 9, 10 ** 9, v, 6)
        elif isinstance(v, list):
            data[k] = [x.strip() for x in
                       ask("新值（逗号分隔）", ",".join(str(x) for x in v)).split(",")
                       if x.strip()]
        else:
            data[k] = ask("新值", v)
        save_fn(data)
        ok(f"{label_map.get(k, k)} = {data[k]}")