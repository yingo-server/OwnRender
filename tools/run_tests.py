#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑 tests/ 下的全部测试。

- 装了 pytest：直接调用 pytest（CI 走这条路）
- 没装 pytest：退化成本脚本自带的极简 runner（只要求测试是普通函数）
  这样**开发环境零依赖也能跑守门测试**（agent.md §0.9）。

用法：
    python tools/run_tests.py [-v] [tests/test_xxx.py ...]
"""
import argparse
import importlib.util
import sys
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _mini_runner(files, verbose=False):
    # 注入 pytest 桩（测试文件只 import pytest，不用其 fixture）
    if "pytest" not in sys.modules:
        try:
            import pytest                                    # noqa: F401
        except Exception:                                    # noqa: BLE001
            sys.modules["pytest"] = types.ModuleType("pytest")

    ok = fail = 0
    for f in files:
        name = f.stem
        spec = importlib.util.spec_from_file_location(name, f)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:                               # noqa: BLE001
            print("❌ 导入失败 %s: %s" % (name, e))
            fail += 1
            continue
        fns = [n for n in dir(mod) if n.startswith("test_")]
        for fn_name in sorted(fns):
            fn = getattr(mod, fn_name)
            if not callable(fn):
                continue
            try:
                fn()
                ok += 1
                if verbose:
                    print("✅ %s::%s" % (name, fn_name))
            except Exception as e:                           # noqa: BLE001
                fail += 1
                print("❌ %s::%s — %s: %s" % (name, fn_name, type(e).__name__, e))
                if verbose:
                    traceback.print_exc()
    print("\n%s" % ("=" * 56))
    print("测试：%d 通过 / %d 失败" % (ok, fail))
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()

    files = [Path(p) for p in a.files] if a.files else \
        sorted((ROOT / "tests").glob("test_*.py"))
    if not files:
        print("没有找到测试")
        return 1

    try:
        import pytest                                        # noqa: F401
        args = ["-q"] + (["-v"] if a.verbose else []) + [str(f) for f in files]
        return int(pytest.main(args))
    except ImportError:
        print("（未安装 pytest，使用内置极简 runner）")
        return _mini_runner(files, a.verbose)


if __name__ == "__main__":
    sys.exit(main())