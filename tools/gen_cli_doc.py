#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成面向 AI 的命令行参数文档（信息密集 / 结构固定 / 便于检索）

产物：
  docs/cli-args.json     机器可读规格：稳定键名、无歧义、可直接被程序或 AI 消费
  docs/CLI-参数.ai.md    人和 AI 都能极速定位的密集文档（表格 + 现成命令 + 排错表）

为什么用生成而不是手写：
  参数定义在 frame_interact/cli.py，可选值与默认值在 config.py。手写文档迟早漂移，
  这里直接 introspect 那两个文件，CI 每次构建都会重新生成并随文档包发布。

用法：
  python tools/gen_cli_doc.py            # 写到 docs/
  python tools/gen_cli_doc.py --check    # 只校验（生成结果与磁盘一致则退出 0）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config                                    # noqa: E402
from frame_interact import cli as _cli           # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# 人工补充层：只写"代码里读不出来的语义/交互/失败模式"，键 = 主长参数名
# ─────────────────────────────────────────────────────────────────────
SEM = {
    "--ai": dict(
        semantics="走云端 API 生成底图，再叠字。**没有 --offline-bg / -i 时就是它**。需 token。",
        interactions=["需要 --token 或已保存的配置；离线环境改用 --offline-bg"],
        example='agnes-render --ai -t "海压竹枝低复举" -y',
        failure=["无 token → exit 1（提示 需要 --token 或配置）",
                 "网络/服务不可达 → exit 1（底图生成失败）"]),
    "--offline-bg": dict(
        semantics="用**内置底图**（background/ 里的图）做真实光照计算 + 叠字，全程离线。",
        interactions=["等价于 --background NAME（历史别名，已自动归一）",
                      "与 -i 互斥：同时给时以 -i 为准（自定义图优先）"],
        example='agnes-render --offline-bg 微水泥 -y',
        failure=["NAME 不存在 → exit 1（未在 background/ 找到底图）；先 --list-backgrounds"]),
    "-i": dict(
        semantics="用**你自己的图片**做光照 + 叠字（不做 AI 生成）。",
        interactions=["支持 png/jpg/jpeg/webp/bmp", "与 --offline-bg 同时给时本项优先"],
        example='agnes-render -i /sdcard/in/wall.png -t "字" -y',
        failure=["路径不存在 → exit 1（图片不存在）", "格式不支持 → exit 1（无法读取）"]),
    "--background": dict(
        semantics="指定内置底图名（与 --offline-bg 同义）。", interactions=[],
        example='agnes-render --offline-bg 微水泥 --background 微水泥 -y', failure=[]),
    "--keep-lit": dict(
        semantics="保留中间产物「光照底图」，便于只换文字时不重复算光照。",
        interactions=["会与 --no-render 一起用于「只出光照图」的流水线"],
        example='agnes-render --offline-bg 微水泥 --keep-lit -y', failure=[]),
    "-t": dict(
        semantics="要叠的字（可含换行：字面 \\n 会被按行拆分处理）。",
        interactions=["缺省时进入交互式 TUI 提示输入", "AI 调用务必传它 + -y"],
        example='agnes-render --offline-bg 微水泥 -t "第一行\\n第二行" -y', failure=[]),
    "-o": dict(
        semantics="输出目录。缺省为包内/工作目录下的 output/。",
        interactions=["Android 建议显式传 -o /sdcard/...", "目录不存在会自动创建"],
        example='agnes-render --offline-bg 微水泥 -o /sdcard/Pictures -y', failure=[]),
    "--output-name": dict(
        semantics="输出文件名（不含扩展名）。缺省按时间戳命名，便于批量时固定名字。",
        interactions=["配合 -o 可得到确定路径：<o>/<output-name>_final.png"],
        example='agnes-render --offline-bg 微水泥 --output-name cover -y', failure=[]),
    "-f": dict(
        semantics="字体名或字体文件路径（fonts/ 下按名匹配，支持 ttf/otf/ttc/otc/woff/woff2）。",
        interactions=["缺省用内置字体", "先用 --list-fonts 看可用名"],
        example='agnes-render --offline-bg 微水泥 -f 草檀斋毛泽东字体 -y', failure=["名字不存在 → exit 1"]),
    "--font-ratio": dict(
        semantics="字号相对画面高度的比例（浮点）。越大字越大。",
        interactions=["与 --font-anchor / --font-pos-* 共同决定版面"], example="--font-ratio 0.18"),
    "--font-anchor": dict(
        semantics="文字锚点（九宫格）。", interactions=["与 --font-pos-x/y 互斥：给了坐标则忽略锚点"],
        example="--font-anchor bc", choices_note="center/tl/tr/bl/br/tc/bc/lc/rc"),
    "--font-pos-x": dict(semantics="文字锚点 X 坐标（0~1 相对宽）或像素，按实现取相对值。",
                         interactions=["与 --font-pos-y 成对使用"], example="--font-pos-x 0.5 --font-pos-y 0.8"),
    "--font-pos-y": dict(semantics="文字锚点 Y 坐标（与 --font-pos-x 配对）。",
                         interactions=[], example="--font-pos-y 0.8"),
    "--window-orientation": dict(
        semantics="窗户朝向，决定太阳入射方向。left=朝西，right=朝东；也可用真实罗盘 n/ne/e/se/s/sw/w/nw。",
        interactions=["历史别名 --window-side left|right 会被归一到这里"],
        example="--window-orientation n", choices_note="left/right/n/ne/e/se/s/sw/w/nw"),
    "--window-side": dict(semantics="（隐藏）旧参数，等价 --window-orientation left|right。",
                          interactions=["仅兼容旧脚本用，新代码请用 --window-orientation"], example="--window-side right"),
    "--window-scale": dict(semantics="窗户/投影尺度倍率。", interactions=[], example="--window-scale 1.15"),
    "--grid-rows": dict(semantics="窗格行数（影响投影的光斑形状）。", interactions=["与 --grid-cols / --grid-frame 成组"],
                        example="--grid-rows 3"),
    "--grid-cols": dict(semantics="窗格列数。", interactions=["与 --grid-rows 成组"], example="--grid-cols 2"),
    "--grid-frame": dict(semantics="窗框粗细（相对量）。", interactions=[], example="--grid-frame 0.06"),
    "--shadow-length": dict(semantics="投影长度系数（太阳高度角之外的额外拉长）。",
                            interactions=["--light-level 与 --time 会先决定几何，本项在其上调整"], example="--shadow-length 1.4"),
    "--time": dict(
        semantics="指定时刻（决定太阳高度角/色温）。支持 ISO 与 \"YYYY-MM-DD HH:MM\"。",
        interactions=["不给则取本机时间（NTP，可用 --no-ntp 关）", "与 --lat/--lon 一起才有物理意义"],
        example='--time "2024-06-21 12:00"', failure=["格式错 → 回退本机时间并提示"]),
    "--lat": dict(semantics="纬度（十进制度，北纬为正）。", interactions=["与 --lon 成对", "不给时按定位链获取"],
                  example="--lat 39.9042"),
    "--lon": dict(semantics="经度（十进制度，东经为正）。", interactions=["与 --lat 成对"], example="--lon 116.4074"),
    "--city": dict(semantics="城市名（仅用于展示/日志）。", interactions=[], example='--city 北京'),
    "--no-ntp": dict(semantics="不走 NTP 校时，直接用系统时钟。", interactions=["内网/离线时用"], example="--no-ntp"),
    "--ntp-host": dict(semantics="指定 NTP 服务器。", interactions=["先用 --list-ntp 看内置列表"], example="--ntp-host time.google.com"),
    "--no-gps": dict(semantics="禁止使用 GPS/系统定位（只允许 IP 或手填）。",
                     interactions=["与 --gps 相反；隐私场景用", "不给坐标的离线环境建议配合 --set-location"], example="--no-gps"),
    "--geo-service": dict(semantics="指定 IP 定位服务（先用 --list-services 查看）。", interactions=[], example="--geo-service ipinfo.io"),
    "--gps": dict(semantics="强制走本机 GPS（termux-location / 系统接口 / 缓存）。",
                  interactions=["Termux/Android 用", "宿主未授权时请改 --lat/--lon"], example="--gps --offline-bg 微水泥 -y"),
    "--ip-loc": dict(semantics="强制走 IP 网络定位。", interactions=["需要联网"], example="--ip-loc"),
    "--set-location": dict(semantics="把坐标写进本机缓存（LAT,LON[,CITY]），之后 --gps 一键命中。",
                           interactions=["一次性动作：执行后 exit 0", "顺带写缓存，不做渲染"],
                           example='--set-location "39.9042,116.4074,北京"',
                           failure=["格式错 → exit 1（行为 lat,lon[,city]）"]),
    "--weather": dict(semantics="天气预设，影响云量/能见度/湿度/降水，进而影响光照强度与色偏。",
                      interactions=["预设值会被 --cloud/--precip/--visibility/--humidity 逐个覆盖",
                                    "auto = 调 API 查询（需联网/定位）"],
                      example="--weather clear", choices_note="auto/clear/cloudy/overcast/rain/snow/haze"),
    "--cloud": dict(semantics="云量（百分，0=晴）→ 削弱直射光，增强漫射。", units="0~100", interactions=["覆盖 --weather 预设"], example="--cloud 80"),
    "--precip": dict(semantics="降水强度（0~100）→ 受影响的可达性/湿润感。", units="0~100", interactions=[], example="--precip 60"),
    "--visibility": dict(semantics="能见度（米，越大越通透；预设晴天为 20000）。", units="米", interactions=[], example="--visibility 5000"),
    "--humidity": dict(semantics="相对湿度（百分）。", units="0~100", interactions=[], example="--humidity 70"),
    "-r": dict(semantics="输出尺寸档（与 -a 纵横比共同决定像素，如 2K+16:9=2048x1152）。",
               interactions=["仅 AI 生成模式下会传给上游 API；离线模式用于画布尺寸", "先用 --list-sizes 看全部组合"],
               example="-r 2K -a 16:9", choices_note="1K/2K/3K/4K"),
    "-a": dict(semantics="输出纵横比。", interactions=["与 -r 组合", "先用 --list-sizes 看映射表"],
               example="-a 9:16", choices_note="1:1/3:4/4:3/16:9/9:16/2:3/3:2/21:9"),
    "--light-level": dict(semantics="光照档位（0~12），按时间自动分类的等级；显式给出可覆盖自动判定。",
                          units="0~12", interactions=["--time/--weather 先算，再被本项覆盖"],
                          example="--light-level 6", failure=["超范围 → argparse 报错 exit 2"]),
    "--wall-desc": dict(semantics="墙面材质描述（自然语言），只影响 AI 生成阶段的提示词。",
                        interactions=["仅 --ai 生效；离线模式无效"], example='--wall-desc "斑驳的老水泥墙"'),
    "--ssaa": dict(semantics="超采样倍数（1=关，越大越慢越干净）。",
                   interactions=["耗时与倍率近似平方关系，4K 建议 <=2"], example="--ssaa 2"),
    "--seed": dict(semantics="随机种子（固定后噪声/纹理可复现）。",
                   interactions=["配合 --no-render/--show-config 做可复现实验"], example="--seed 12345"),
    "--cinnabar": dict(semantics="朱砂/主色 RGB（三个 0~255 整数），覆盖默认色。",
                       interactions=["nargs=3", "影响材质基色与光照耦合结果"],
                       example="--cinnabar 180 40 30"),
    "--noise-low": dict(semantics="低频噪声强度（大尺度起伏）。", interactions=["与 --noise-mid/--noise-high 成组"], example="--noise-low 0.4"),
    "--noise-mid": dict(semantics="中频噪声强度（主颗粒感）。", interactions=[], example="--noise-mid 0.5"),
    "--noise-high": dict(semantics="高频噪声强度（细砂感）。", interactions=[], example="--noise-high 0.3"),
    "--diffusion": dict(semantics="光扩散/柔化强度。", interactions=["越大阴影越软"], example="--diffusion 1.2"),
    "--oxidation": dict(semantics="氧化/做旧程度。", interactions=[], example="--oxidation 0.35"),
    "--shadow-strength": dict(semantics="阴影浓度（0=无影）。", interactions=["与 --light-level 一起决定画面明暗结构"], example="--shadow-strength 0.8"),
    "--material-coupling": dict(semantics="字形随墙面材质起伏的耦合强度（0=关闭）。",
                                interactions=["值越大字越「融进」墙里"], example="--material-coupling 0.6"),
    "--exposure": dict(semantics="画面曝光倍率（>1 更亮）。", interactions=["后期参数，不改变照明计算"], example="--exposure 1.15"),
    "--saturation": dict(semantics="画面饱和度倍率（1=原始）。", interactions=[], example="--saturation 0.9"),
    "--token": dict(semantics="AI 服务令牌（仅 --ai 模式需要）。",
                    interactions=["也可用环境变量 AGNES_API_TOKEN，或先写进配置"],
                    example='--token "xxx"', failure=["缺失 → exit 1（需要 --token 或配置）"]),
    "--settings": dict(semantics="打开设置面板（交互式）。", interactions=["非交互终端会退化"], example="--settings"),
    "--no-color": dict(semantics="关闭 ANSI 颜色（日志更易被程序解析）。",
                       interactions=["等价环境变量 NO_COLOR=1", "AI/CI 调用建议总是加"],
                       example="--no-color"),
    "-y": dict(semantics="对所有确认直接 yes（非交互必需）。",
               interactions=["无 -y 且无 TTY 时会等待/退化", "AI 调用务必加"],
               example="-y", failure=["非交互又没 -y → 可能 exit 2 或长时间等待"]),
    "-v": dict(semantics="详细日志（DEBUG）。", interactions=["输出更多可解析字段，如辐照度/可达性"], example="-v"),
    "--log-level": dict(semantics="日志级别。", interactions=["覆盖 -v 的默认级别"], example="--log-level DEBUG",
                        choices_note="DEBUG/INFO/WARN/ERROR"),
    "--log-file": dict(semantics="把日志写入文件（默认 output/ 下）。", interactions=["配合 -v 便于事后排错"], example="--log-file"),
    "--dry-run": dict(semantics="演练：解析参数与配置，但不真正渲染/请求。", interactions=["用于排查参数", "exit 0 不代表渲染可用"], example="--dry-run"),
    "--no-render": dict(semantics="只做前置步骤（如生成/光照底图），跳过最终叠字与渲染。",
                        interactions=["配合 --keep-lit 得到中间产物"], example="--no-render --keep-lit"),
    "--list-fonts": dict(semantics="列出可用字体（名 → 路径）。", interactions=["只读查询，exit 0"], example="--list-fonts --no-color"),
    "--list-backgrounds": dict(semantics="列出内置底图名。", interactions=["只读查询"], example="--list-backgrounds --no-color"),
    "--list-ntp": dict(semantics="列出内置 NTP 服务器。", interactions=["只读查询"], example="--list-ntp"),
    "--list-services": dict(semantics="列出内置 IP 定位服务。", interactions=["只读查询"], example="--list-services"),
    "--list-sizes": dict(semantics="列出 (档位, 纵横比) → 像素 的完整映射。", interactions=["选 -r/-a 前查这里"], example="--list-sizes"),
    "--show-config": dict(semantics="打印当前生效配置（含来源）。", interactions=["排错首选"], example="--show-config"),
    "--reset-config": dict(semantics="恢复出厂配置。", interactions=["会写配置文件（破坏性）", "建议先 --show-config 备份"], example="--reset-config"),
    "--version": dict(semantics="打印版本号后退出。", interactions=["argparse 内建 action=version"], example="--version"),
}

ENV_VARS = [
    ("OWNRENDER_HOME", "便携根目录：优先用它定位 background/ fonts/ config/ output/。设为某目录后，素材/配置/输出都跟随它。", "OWNRENDER_HOME=/sdcard/ow ./ownrender -y"),
    ("OWNRENDER_ASCII", "强制用 ASCII 符号渲染终端输出（无 Unicode 的终端/日志）。", "OWNRENDER_ASCII=1"),
    ("OWNRENDER_UNICODE", "强制 Unicode（覆盖自动探测）。", "OWNRENDER_UNICODE=1"),
    ("OWNRENDER_NO_REEXEC", "禁止自我重启（打包/验收环境用，避免进程被替换）。", "OWNRENDER_NO_REEXEC=1"),
    ("NO_COLOR", "任何非空值＝关闭 ANSI 颜色（与 --no-color 等价）。", "NO_COLOR=1"),
    ("FORCE_COLOR", "强制开启颜色（覆盖自动探测）。", "FORCE_COLOR=1"),
    ("AGNES_API_TOKEN", "AI 模式令牌的环境变量形式（优先级低于 --token 之外，见 config）。", 'AGNES_API_TOKEN=xxx'),
    ("TZ", "时区；影响默认时间与太阳位置推算（POSIX 名优先）。", "TZ=Asia/Shanghai"),
    ("XDG_CONFIG_HOME", "配置目录（安装目录只读时，配置落到 $XDG_CONFIG_HOME/ownrender）。", "XDG_CONFIG_HOME=/tmp/cfg"),
    ("LC_ALL / LANG / LANGUAGE", "影响终端编码探测与提示语言选择；哑终端下 LC_ALL=C 也能正常出图（已验证）。", "LC_ALL=C"),
]

EXIT_CODES = [
    ("0", "成功（含 --dry-run / --no-render / 只读查询 / --set-location）"),
    ("1", "运行期错误：缺 token、底图/图片/字体不存在、定位失败、叠字失败、参数格式错"),
    ("2", "用法错误：未知参数、choices 越界（argparse 打印帮助并退出）"),
    ("130", "用户中断（Ctrl-C / TUI 里取消）"),
]

MODE_TABLE = [
    ("tui", "无参数交互式界面", "agnes-render", "有 TTY 时进入 TUI；非 TTY 自动退化打印 --help"),
    ("ai", "云端生成底图 + 叠字", "agnes-render --ai -t \"...\" -y", "需要 token；产出 raw 底图与 final 成图"),
    ("offline", "内置底图 + 真实光照计算 + 叠字", "agnes-render --offline-bg 微水泥 -t \"...\" -y", "全程离线，最常用；物理光照可按时间/坐标/天气调整"),
    ("custom", "自有图片 + 光照 + 叠字", "agnes-render -i in.png -t \"...\" -y", "不做 AI 生成，Pillow 读入后走同一条渲染链"),
]

RECIPES = [
    ("最小可用（离线，无需网络/坐标）", 'agnes-render --offline-bg 微水泥 -t "字" -y --no-color'),
    ("确定性输出路径（推荐给自动化）", 'agnes-render --offline-bg 微水泥 -t "字" -o /tmp/out --output-name cover -y --no-color'),
    ("指定时间 + 坐标 + 天气（物理光照最准）", 'agnes-render --offline-bg 微水泥 --time "2024-06-21 12:00" --lat 39.9042 --lon 116.4074 --weather clear -t "字" -y'),
    ("固定随机种子做可复现实验", 'agnes-render --offline-bg 微水泥 --seed 12345 --ssaa 1 -t "字" -y'),
    ("只出光照底图（中间产物）", 'agnes-render --offline-bg 微水泥 --keep-lit --no-render -y'),
    ("列出可用资源（机器可解析）", 'agnes-render --list-fonts --list-backgrounds --no-color'),
    ("写定位缓存，后续 --gps 一键用", 'agnes-render --set-location "39.9042,116.4074,北京"'),
    ("CI/容器里跑（无 TTY、无 locale）", 'LC_ALL=C NO_COLOR=1 agnes-render --offline-bg 微水泥 -t "字" -y --no-color'),
    ("Android/Termux 嵌入调用", 'agnes-render --offline-bg 微水泥 -o /sdcard/Pictures -y --no-color   # 坐标用 --lat/--lon 或 --set-location'),
]

FAILURE_MAP = [
    ("exit=2 且没有输出", "参数名拼错 / choices 越界", "agnes-render --help；或核对本文档的取值列"),
    ("提示「未在 background/ 找到底图」", "底图名不对或素材目录不在便携根", "agnes-render --list-backgrounds；必要时设 OWNRENDER_HOME"),
    ("「需要 --token 或配置」", "--ai 模式没给令牌", "--token 或 export AGNES_API_TOKEN，或改用 --offline-bg / -i"),
    ("「位置解析失败」", "定位链全失败（无 GPS、无网、无坐标）", "直接 --lat/--lon，或先 --set-location 写缓存"),
    ("等很久没有输出", "非交互环境里在等确认", "加 -y"),
    ("颜色转义污染日志", "ANSI 颜色", "--no-color 或 NO_COLOR=1"),
    ("容器里中文报编码错", "locale 不是 UTF-8", "LC_ALL=C 也能跑（已验证）；或设 PYTHONUTF8=1"),
    ("ImportError: libblas/libgfortran/libjpeg...", "下载的二进制包缺系统库（打包问题）", "重新下载最新 Release；打包脚本会用 DT_NEEDED 自动补系统库"),
]


def _type_name(action):
    t = action.type
    if t is float:
        return "float"
    if t is int:
        return "int"
    if t is str or t is None:
        return "str"
    return getattr(t, "__name__", "str")


def collect():
    parser = _cli.build_parser()
    groups = []
    for grp in parser._action_groups:                    # noqa: SLF001
        title = grp.title or ""
        if title.lower().startswith("positional") or title.lower().startswith("options"):
            continue
        items = []
        for a in grp._group_actions:                     # noqa: SLF001
            if a.help == argparse.SUPPRESS:
                hidden = True
            else:
                hidden = False
            longs = [o for o in a.option_strings if o.startswith("--")]
            prim = longs[0] if longs else (a.option_strings[0] if a.option_strings else a.dest)
            meta = SEM.get(prim, {})
            entry = {
                "flag": prim,
                "aliases": a.option_strings,
                "group": title,
                "takes_value": not isinstance(a, (argparse._StoreTrueAction,   # noqa: SLF001
                                                  argparse._StoreFalseAction,
                                                  argparse._VersionAction)),
                "metavar": a.metavar if isinstance(a.metavar, str) else None,
                "type": "bool" if not hasattr(a, "type") or a.type is None else _type_name(a),
                "choices": (sorted(map(str, a.choices)) if a.choices is not None
                            and not isinstance(a.choices, range) else
                            ("%d~%d" % (a.choices.start, a.choices.stop - 1)
                             if isinstance(a.choices, range) else None)),
                "nargs": a.nargs,
                "default": None if a.default is None else str(a.default),
                "help": (a.help or ""),
                "hidden": hidden,
                "semantics": meta.get("semantics", (a.help or "")),
                "units": meta.get("units"),
                "interactions": meta.get("interactions", []),
                "example": meta.get("example"),
                "failure_modes": meta.get("failure", []),
                "choices_note": meta.get("choices_note"),
            }
            items.append(entry)
        if items:
            groups.append({"group": title, "args": items})
    return parser, groups


def build_spec(parser, groups):
    return {
        "prog": config.PROG,
        "version": config.VERSION,
        "source_of_truth": ["frame_interact/cli.py", "config.py"],
        "generated_by": "tools/gen_cli_doc.py",
        "modes": [{"key": k, "desc": d, "cmd": c, "notes": n} for k, d, c, n in MODE_TABLE],
        "env": [{"name": n, "semantics": s, "example": e} for n, s, e in ENV_VARS],
        "exit_codes": [{"code": c, "meaning": m} for c, m in EXIT_CODES],
        "outputs": {
            "default_dir": "output/（可用 -o 覆盖）",
            "final_image": "<output-dir>/<name>_final.png（--output-name 可固定 name）",
            "intermediate": "光照底图 / raw 底图（--keep-lit 时保留）",
            "stdout_fields": ["字体", "成品", "耗时", "光照 <n>ms", "辐照度", "可达性"],
            "parse_hint": "要机器可读，请固定 -o 与 --output-name，并加 --no-color -y",
        },
        "choices": {
            "resolution": config.SIZE_TIERS,
            "aspect": config.ASPECT_RATIOS,
            "anchor": config.ANCHORS,
            "window_orientation": config.WINDOW_ORIENTATIONS,
            "weather": config.WEATHER_TYPES,
            "font_ext": sorted(config.FONT_EXTENSIONS),
            "image_ext": sorted(config.IMAGE_EXTENSIONS),
        },
        "weather_presets": getattr(config, "WEATHER_PRESETS", {}),
        "args": [{"group": g["group"], **a} for g in groups for a in g["args"]],
        "recipes": [{"desc": d, "cmd": c} for d, c in RECIPES],
        "failure_map": [{"symptom": s, "cause": c, "fix": f} for s, c, f in FAILURE_MAP],
    }


def render_md(spec):
    L = []
    p = L.append
    p("# %s — 命令行参数（AI 速查版）" % spec["prog"])
    p("")
    p("> 版本 `%s` · 本文件由 `tools/gen_cli_doc.py` 从 `frame_interact/cli.py` + `config.py`"
      " 自动生成（CI 每次构建重新生成，不会与代码漂移）。" % spec["version"])
    p("> 机器可读版本：`docs/cli-args.json`（键名稳定，可直接被程序/AI 消费）。")
    p("")
    p("## 0. 给 AI 的调用铁律")
    p("")
    p("- **非交互调用永远带 `-y --no-color`**；要确定性产物再加 `-o <dir> --output-name <name>`。")
    p("- 离线优先：`--offline-bg <名字>` 不联网即可出图；联网定位/天气才需要 `--lat/--lon`。")
    p("- 无 TTY 时会自动退化到参数模式（不会卡在 TUI），但**没有 `-y` 仍可能等待确认**。")
    p("- 退出码：`0` 成功 / `1` 运行错 / `2` 用法错 / `130` 中断。")
    p("- 想只取资源清单：`--list-fonts --list-backgrounds --list-sizes --show-config`（都是只读、exit 0）。")
    p("")
    p("## 1. 四种模式")
    p("")
    p("| key | 说明 | 典型命令 | 备注 |")
    p("|---|---|---|---|")
    for m in spec["modes"]:
        p("| `%s` | %s | `%s` | %s |" % (m["key"], m["desc"], m["cmd"], m["notes"]))
    p("")
    p("## 2. 环境变量")
    p("")
    p("| 变量 | 语义 | 示例 |")
    p("|---|---|---|")
    for e in spec["env"]:
        p("| `%s` | %s | `%s` |" % (e["name"], e["semantics"], e["example"]))
    p("")
    p("## 3. 退出码")
    p("")
    p("| 码 | 含义 |")
    p("|---|---|")
    for c in spec["exit_codes"]:
        p("| `%s` | %s |" % (c["code"], c["meaning"]))
    p("")
    p("## 4. 产物与可解析字段")
    p("")
    o = spec["outputs"]
    p("- 默认输出目录：`%s`" % o["default_dir"])
    p("- 成图：`%s`" % o["final_image"])
    p("- 中间产物：%s" % o["intermediate"])
    p("- stdout 可解析字段：%s" % "、".join("`%s`" % x for x in o["stdout_fields"]))
    p("- 解析建议：%s" % o["parse_hint"])
    p("")
    p("## 5. 参数总表（按功能分组）")
    p("")
    for g in {a["group"]: None for a in spec["args"]}:
        p("### %s" % g)
        p("")
        p("| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |")
        p("|---|---|---|---|---|---|")
        for a in spec["args"]:
            if a["group"] != g:
                continue
            if a["takes_value"]:
                vals = a["choices_note"] or (
                    "`%s`" % "|".join(a["choices"]) if a["choices"] else (a["type"] or "str"))
            else:
                vals = "（开关）"
            dft = a["default"] if a["default"] is not None else "—"
            sem = a["semantics"].replace("\n", " ")
            if a["hidden"]:
                sem = "（隐藏参数）" + sem
            inter = "；".join(a["interactions"]) or "—"
            ex = ("`%s`" % a["example"]) if a["example"] else "—"
            p("| `%s` | %s | %s | %s | %s | %s |"
              % (a["flag"], vals, dft, sem, inter, ex))
        p("")
    p("## 6. 现成命令（可直接复制）")
    p("")
    for r in spec["recipes"]:
        p("- **%s**" % r["desc"])
        p("")
        p("  ```bash")
        p("  %s" % r["cmd"])
        p("  ```")
    p("")
    p("## 7. 报错 → 原因 → 处理")
    p("")
    p("| 现象 | 原因 | 处理 |")
    p("|---|---|---|")
    for f in spec["failure_map"]:
        p("| %s | %s | %s |" % (f["symptom"], f["cause"], f["fix"]))
    p("")
    p("## 8. 取值枚举（程序可直接用）")
    p("")
    for k, v in spec["choices"].items():
        p("- `%s`: %s" % (k, ", ".join("`%s`" % x for x in v)))
    p("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验生成结果是否与磁盘一致")
    ap.add_argument("--out-dir", default=str(ROOT / "docs"))
    a = ap.parse_args()

    parser, groups = collect()
    spec = build_spec(parser, groups)
    js = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    md = render_md(spec)

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {out / "cli-args.json": js, out / "CLI-参数.ai.md": md}

    if a.check:
        bad = [str(p) for p, want in files.items()
               if (not p.exists()) or p.read_text(encoding="utf-8") != want]
        for p in bad:
            print("不一致：%s" % p)
        print("参数 %d 个 / 分组 %d 个" % (len(spec["args"]), len(groups)))
        return 1 if bad else 0

    for p, txt in files.items():
        p.write_text(txt, encoding="utf-8")
        print("已写出 %s（%d 字节）" % (p, len(txt.encode())))
    print("参数 %d 个 / 分组 %d 个" % (len(spec["args"]), len(groups)))
    return 0


if __name__ == "__main__":
    sys.exit(main())