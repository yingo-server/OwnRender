#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agnes-render V35 主入口

职责（只做 3 件事）：
  1. 初始化配置
  2. 引入交互子框架
  3. 交给交互层 dispatch

不含任何业务逻辑。交互层负责再引入光照/渲染子框架。
"""
import sys
from pathlib import Path

# 确保项目根在 sys.path（便于子目录 import）
_PROJ_ROOT = Path(__file__).parent.resolve()
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))


def run_args(argv=None) -> int:
    """
    纯参数入口（供打包后的可执行文件 / Android .so / JNI / 宿主程序调用）。
    只解析参数并执行，不进入交互 TUI。
    """
    import config
    config.ensure_utf8_stdio()          # 先保证终端编码不会让输出崩掉
    config.ensure_config_files()
    import frame_interact
    if argv is None:
        argv = sys.argv[1:]
    return frame_interact.run(list(argv))


def main() -> int:
    # 1. 初始化配置（首次生成 / 缺失键自动补全）
    import config
    config.ensure_utf8_stdio()          # 先保证终端编码不会让输出崩掉
    config.ensure_config_files()
    # 2. 引入交互子框架（它内部会引入 light / render）
    import frame_interact

    # 3. 交给交互层
    return frame_interact.run(sys.argv[1:])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  - 已中断\n")
        sys.exit(130)