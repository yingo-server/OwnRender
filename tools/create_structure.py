#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建 agnes-render V35 空白文件结构

用法：
    mkdir agnes-render && cd agnes-render
    python create_structure.py

已存在的文件会被跳过，不会覆盖。
"""

import sys
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════
# 结构定义
# 路径以 "/" 结尾 → 目录；否则 → 文件（写入 docstring 说明职责）
# ═══════════════════════════════════════════════════════════════════
STRUCTURE = {

    # ── 顶层 ──────────────────────────────────────────────────────
    "main.py":
        "agnes-render V35 主入口\n"
        "职责：初始化配置 → 引入 3 个子框架 → 交给交互层\n"
        "Level 1 只做 3 件事，不含任何业务逻辑",

    "config.py":
        "配置持久化层\n"
        "职责：JSON 读写、出厂值、配置注入\n"
        "被所有子框架读取；不依赖项目内其他模块",

    # ── 光照子框架 ────────────────────────────────────────────────
    "frame_light/": {
        "__init__.py":
            "光照子框架入口\n"
            "只 re-export：compute_light, compute_scene_lights, LightResult",
        "utils.py":
            "光照工具（本框架专用，不 import 本框架其他文件）\n"
            "srgb_to_linear / linear_to_srgb / _stable_seed / clamp / smoothstep",
        "astro.py":
            "天文 + 物理 + 环境数据\n"
            "日月位置、大气质量、黑体辐射、天气 API、NTP、地理定位\n"
            "只 import utils.py",
        "geometry.py":
            "光斑几何\n"
            "位置 / 大小 / 半影 / 阴影 / 方位词\n"
            "只 import utils.py",
        "scene.py":
            "4 层光照向量\n"
            "ambient / sky / ground / direct\n"
            "只 import utils.py",
        "light.py":
            "光照编排\n"
            "串 astro + geometry + scene → 对外暴露 compute_light\n"
            "import utils / astro / geometry / scene",
    },

    # ── 渲染子框架 ────────────────────────────────────────────────
    "frame_render/": {
        "__init__.py":
            "渲染子框架入口\n"
            "只 re-export：generate_lit_wall, render_fusion",
        "utils.py":
            "渲染工具（本框架专用，不 import 本框架其他文件）\n"
            "cv2 模糊 / 重采样 / perlin / fbm / median / ACES / srgb",
        "retinex.py":
            "Retinex 分解 + 材质分析\n"
            "I = R × S，工作尺寸（≤1024），异常检测，裂纹内渗\n"
            "只 import utils.py",
        "patch.py":
            "光斑 mask 渲染（15 层）\n"
            "窗格 / 玻璃 / 透射 / 窗框 / 污渍 / 水痕 / 焦散 / 灰尘\n"
            "Bloom / 玻璃结构 / 裂纹 / 微凸起 / 半影 / 菲涅尔 / 光渗 / 年代感\n"
            "只 import utils.py",
        "compose.py":
            "主合成 + 相机效果\n"
            "ACES tone mapping / 5 层光照合成 / 光斑反弹 / 渐晕 / 阴影色偏 / CMOS\n"
            "只 import utils.py",
        "text.py":
            "文字渲染\n"
            "SSAA / 智能断行 / 年代感 / 材质耦合 / 融合\n"
            "只 import utils.py",
        "pipeline.py":
            "渲染编排\n"
            "串 retinex → patch → compose → text\n"
            "import utils / retinex / patch / compose / text",
    },

    # ── 交互子框架 ────────────────────────────────────────────────
    "frame_interact/": {
        "__init__.py":
            "交互子框架入口\n"
            "只 re-export：run",
        "utils.py":
            "交互工具（本框架专用，不 import 本框架其他文件）\n"
            "终端常量 / _init_term / _trunc / 颜色",
        "cli.py":
            "CLI 解析 + 询问原语\n"
            "argparse / ask / ask_yn / ask_multiline / menu / field\n"
            "只 import utils.py",
        "progress.py":
            "进度条三件套\n"
            "ProgressBar / Spinner / GlobalProgress\n"
            "只 import utils.py",
        "settings.py":
            "设置菜单 + 信息菜单\n"
            "凭证 / 提示词 / 渲染 / 光照 / 天气 / 日志 / 恢复出厂\n"
            "信息：字体 / 底图 / 尺寸 / NTP / 地理\n"
            "import utils / cli / progress + config",
        "offline.py":
            "离线模式编排\n"
            "底图 → 时间/位置/天气 → 光照 → 渲染 → 叠字\n"
            "调用 frame_light / frame_render 的对外接口",
        "ai.py":
            "AI 模式编排\n"
            "Token → 时间/位置/天气 → 光照 → 提示词 → API → 叠字\n"
            "调用 frame_light / frame_render 的对外接口",
        "runner.py":
            "交互主编排（含主菜单循环）\n"
            "解析 CLI → dispatch → 主菜单循环\n"
            "import cli / settings / offline / ai",
    },
}


# ═══════════════════════════════════════════════════════════════════
# 创建逻辑
# ═══════════════════════════════════════════════════════════════════
def create_structure(base_dir="."):
    base = Path(base_dir).resolve()
    created_files = 0
    created_dirs = 0
    skipped = 0

    def walk(struct, prefix=Path(".")):
        nonlocal created_files, created_dirs, skipped
        for name, value in struct.items():
            if name.endswith("/"):
                # 目录
                dir_name = name.rstrip("/")
                dir_path = base / prefix / dir_name
                rel = dir_path.relative_to(base)
                if not dir_path.exists():
                    dir_path.mkdir(parents=True)
                    created_dirs += 1
                    print(f"  [DIR ]  {rel}/")
                else:
                    print(f"  [SKIP]  {rel}/")
                walk(value, prefix / dir_name)
            else:
                # 文件
                file_path = base / prefix / name
                rel = file_path.relative_to(base)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                if not file_path.exists():
                    content = (
                        "#!/usr/bin/env python3\n"
                        "# -*- coding: utf-8 -*-\n"
                        '"""\n'
                        f"{value}\n"
                        '"""\n'
                    )
                    file_path.write_text(content, encoding="utf-8")
                    created_files += 1
                    print(f"  [FILE]  {rel}")
                else:
                    skipped += 1
                    print(f"  [SKIP]  {rel}")

    print(f"创建 agnes-render V35 空白结构")
    print(f"目标目录：{base}")
    print("─" * 56)
    walk(STRUCTURE)
    print("─" * 56)
    print(f"完成：{created_dirs} 目录  {created_files} 文件创建  "
          f"{skipped} 跳过")
    print()
    print("后续步骤：")
    print("  1. 打开各文件，按 docstring 职责填充代码")
    print("  2. 每写完一批，运行：")
    print("       python -c 'import main; print(\"OK\")'")
    print("  3. 依赖规则（严格单向）：")
    print("       小文件 → 本框架 utils.py → config.py")
    print("       编排文件 → 本框架多个小文件")
    print("       __init__.py → 只 re-export")
    print("       子框架之间不互相 import（仅编排层通过 __init__ 调用）")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    create_structure(target)