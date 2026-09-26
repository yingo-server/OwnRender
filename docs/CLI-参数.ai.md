# agnes-render — 命令行参数（AI 速查版）

> 版本 `10.0.0` · 本文件由 `tools/gen_cli_doc.py` 从 `frame_interact/cli.py` + `config.py` 自动生成（CI 每次构建重新生成，不会与代码漂移）。
> 机器可读版本：`docs/cli-args.json`（键名稳定，可直接被程序/AI 消费）。

## 0. 给 AI 的调用铁律

- **非交互调用永远带 `-y --no-color`**；要确定性产物再加 `-o <dir> --output-name <name>`。
- 离线优先：`--offline-bg <名字>` 不联网即可出图；联网定位/天气才需要 `--lat/--lon`。
- 无 TTY 时会自动退化到参数模式（不会卡在 TUI），但**没有 `-y` 仍可能等待确认**。
- 退出码：`0` 成功 / `1` 运行错 / `2` 用法错 / `130` 中断。
- 想只取资源清单：`--list-fonts --list-backgrounds --list-sizes --show-config`（都是只读、exit 0）。

## 1. 四种模式

| key | 说明 | 典型命令 | 备注 |
|---|---|---|---|
| `tui` | 无参数交互式界面 | `agnes-render` | 有 TTY 时进入 TUI；非 TTY 自动退化打印 --help |
| `ai` | 云端生成底图 + 叠字 | `agnes-render --ai -t "..." -y` | 需要 token；产出 raw 底图与 final 成图 |
| `offline` | 内置底图 + 真实光照计算 + 叠字 | `agnes-render --offline-bg 微水泥 -t "..." -y` | 全程离线，最常用；物理光照可按时间/坐标/天气调整 |
| `custom` | 自有图片 + 光照 + 叠字 | `agnes-render -i in.png -t "..." -y` | 不做 AI 生成，Pillow 读入后走同一条渲染链 |

## 2. 环境变量

| 变量 | 语义 | 示例 |
|---|---|---|
| `OWNRENDER_HOME` | 便携根目录：优先用它定位 background/ fonts/ config/ output/。设为某目录后，素材/配置/输出都跟随它。 | `OWNRENDER_HOME=/sdcard/ow ./ownrender -y` |
| `OWNRENDER_ASCII` | 强制用 ASCII 符号渲染终端输出（无 Unicode 的终端/日志）。 | `OWNRENDER_ASCII=1` |
| `OWNRENDER_UNICODE` | 强制 Unicode（覆盖自动探测）。 | `OWNRENDER_UNICODE=1` |
| `OWNRENDER_NO_REEXEC` | 禁止自我重启（打包/验收环境用，避免进程被替换）。 | `OWNRENDER_NO_REEXEC=1` |
| `NO_COLOR` | 任何非空值＝关闭 ANSI 颜色（与 --no-color 等价）。 | `NO_COLOR=1` |
| `FORCE_COLOR` | 强制开启颜色（覆盖自动探测）。 | `FORCE_COLOR=1` |
| `AGNES_API_TOKEN` | AI 模式令牌的环境变量形式（优先级低于 --token 之外，见 config）。 | `AGNES_API_TOKEN=xxx` |
| `TZ` | 时区；影响默认时间与太阳位置推算（POSIX 名优先）。 | `TZ=Asia/Shanghai` |
| `XDG_CONFIG_HOME` | 配置目录（安装目录只读时，配置落到 $XDG_CONFIG_HOME/ownrender）。 | `XDG_CONFIG_HOME=/tmp/cfg` |
| `LC_ALL / LANG / LANGUAGE` | 影响终端编码探测与提示语言选择；哑终端下 LC_ALL=C 也能正常出图（已验证）。 | `LC_ALL=C` |

## 3. 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功（含 --dry-run / --no-render / 只读查询 / --set-location） |
| `1` | 运行期错误：缺 token、底图/图片/字体不存在、定位失败、叠字失败、参数格式错 |
| `2` | 用法错误：未知参数、choices 越界（argparse 打印帮助并退出） |
| `130` | 用户中断（Ctrl-C / TUI 里取消） |

## 4. 产物与可解析字段

- 默认输出目录：`output/（可用 -o 覆盖）`
- 成图：`<output-dir>/<name>_final.png（--output-name 可固定 name）`
- 中间产物：光照底图 / raw 底图（--keep-lit 时保留）
- stdout 可解析字段：`字体`、`成品`、`耗时`、`光照 <n>ms`、`辐照度`、`可达性`
- 解析建议：要机器可读，请固定 -o 与 --output-name，并加 --no-color -y

## 5. 参数总表（按功能分组）

### 模式选择

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--ai` | （开关） | False | 走云端 API 生成底图，再叠字。**没有 --offline-bg / -i 时就是它**。需 token。 | 需要 --token 或已保存的配置；离线环境改用 --offline-bg | `agnes-render --ai -t "海压竹枝低复举" -y` |
| `--offline-bg` | bool | — | 用**内置底图**（background/ 里的图）做真实光照计算 + 叠字，全程离线。 | 等价于 --background NAME（历史别名，已自动归一）；与 -i 互斥：同时给时以 -i 为准（自定义图优先） | `agnes-render --offline-bg 微水泥 -y` |
| `--input-image` | bool | — |  | — | — |
| `--background` | bool | — | 指定内置底图名（与 --offline-bg 同义）。 | — | `agnes-render --offline-bg 微水泥 --background 微水泥 -y` |
| `--keep-lit` | （开关） | False | 保留中间产物「光照底图」，便于只换文字时不重复算光照。 | 会与 --no-render 一起用于「只出光照图」的流水线 | `agnes-render --offline-bg 微水泥 --keep-lit -y` |

### 输入输出

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--text` | bool | — |  | — | — |
| `--output` | bool | — |  | — | — |
| `--output-name` | bool | — | 输出文件名（不含扩展名）。缺省按时间戳命名，便于批量时固定名字。 | 配合 -o 可得到确定路径：<o>/<output-name>_final.png | `agnes-render --offline-bg 微水泥 --output-name cover -y` |

### 字体与位置

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--font` | bool | — |  | — | — |
| `--font-ratio` | float | — | 字号相对画面高度的比例（浮点）。越大字越大。 | 与 --font-anchor / --font-pos-* 共同决定版面 | `--font-ratio 0.18` |
| `--font-anchor` | center/tl/tr/bl/br/tc/bc/lc/rc | — | 文字锚点（九宫格）。 | 与 --font-pos-x/y 互斥：给了坐标则忽略锚点 | `--font-anchor bc` |
| `--font-pos-x` | float | — | 文字锚点 X 坐标（0~1 相对宽）或像素，按实现取相对值。 | 与 --font-pos-y 成对使用 | `--font-pos-x 0.5 --font-pos-y 0.8` |
| `--font-pos-y` | float | — | 文字锚点 Y 坐标（与 --font-pos-x 配对）。 | — | `--font-pos-y 0.8` |

### 窗户几何

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--window-orientation` | left/right/n/ne/e/se/s/sw/w/nw | — | 窗户朝向，决定太阳入射方向。left=朝西，right=朝东；也可用真实罗盘 n/ne/e/se/s/sw/w/nw。 | 历史别名 --window-side left|right 会被归一到这里 | `--window-orientation n` |
| `--window-side` | `left|right` | — | （隐藏参数）（隐藏）旧参数，等价 --window-orientation left|right。 | 仅兼容旧脚本用，新代码请用 --window-orientation | `--window-side right` |
| `--window-scale` | float | — | 窗户/投影尺度倍率。 | — | `--window-scale 1.15` |
| `--grid-rows` | int | — | 窗格行数（影响投影的光斑形状）。 | 与 --grid-cols / --grid-frame 成组 | `--grid-rows 3` |
| `--grid-cols` | int | — | 窗格列数。 | 与 --grid-rows 成组 | `--grid-cols 2` |
| `--grid-frame` | float | — | 窗框粗细（相对量）。 | — | `--grid-frame 0.06` |
| `--shadow-length` | bool | — | 投影长度系数（太阳高度角之外的额外拉长）。 | --light-level 与 --time 会先决定几何，本项在其上调整 | `--shadow-length 1.4` |

### 时间与位置

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--time` | bool | — | 指定时刻（决定太阳高度角/色温）。支持 ISO 与 "YYYY-MM-DD HH:MM"。 | 不给则取本机时间（NTP，可用 --no-ntp 关）；与 --lat/--lon 一起才有物理意义 | `--time "2024-06-21 12:00"` |
| `--lat` | float | — | 纬度（十进制度，北纬为正）。 | 与 --lon 成对；不给时按定位链获取 | `--lat 39.9042` |
| `--lon` | float | — | 经度（十进制度，东经为正）。 | 与 --lat 成对 | `--lon 116.4074` |
| `--city` | bool | — | 城市名（仅用于展示/日志）。 | — | `--city 北京` |
| `--no-ntp` | （开关） | False | 不走 NTP 校时，直接用系统时钟。 | 内网/离线时用 | `--no-ntp` |
| `--ntp-host` | bool | — | 指定 NTP 服务器。 | 先用 --list-ntp 看内置列表 | `--ntp-host time.google.com` |
| `--no-gps` | （开关） | False | 禁止使用 GPS/系统定位（只允许 IP 或手填）。 | 与 --gps 相反；隐私场景用；不给坐标的离线环境建议配合 --set-location | `--no-gps` |
| `--geo-service` | bool | — | 指定 IP 定位服务（先用 --list-services 查看）。 | — | `--geo-service ipinfo.io` |
| `--gps` | （开关） | False | 强制走本机 GPS（termux-location / 系统接口 / 缓存）。 | Termux/Android 用；宿主未授权时请改 --lat/--lon | `--gps --offline-bg 微水泥 -y` |
| `--ip-loc` | （开关） | False | 强制走 IP 网络定位。 | 需要联网 | `--ip-loc` |
| `--set-location` | bool | — | 把坐标写进本机缓存（LAT,LON[,CITY]），之后 --gps 一键命中。 | 一次性动作：执行后 exit 0；顺带写缓存，不做渲染 | `--set-location "39.9042,116.4074,北京"` |

### 天气

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--weather` | auto/clear/cloudy/overcast/rain/snow/haze | — | 天气预设，影响云量/能见度/湿度/降水，进而影响光照强度与色偏。 | 预设值会被 --cloud/--precip/--visibility/--humidity 逐个覆盖；auto = 调 API 查询（需联网/定位） | `--weather clear` |
| `--cloud` | float | — | 云量（百分，0=晴）→ 削弱直射光，增强漫射。 | 覆盖 --weather 预设 | `--cloud 80` |
| `--precip` | float | — | 降水强度（0~100）→ 受影响的可达性/湿润感。 | — | `--precip 60` |
| `--visibility` | float | — | 能见度（米，越大越通透；预设晴天为 20000）。 | — | `--visibility 5000` |
| `--humidity` | float | — | 相对湿度（百分）。 | — | `--humidity 70` |

### 输出规格（AI 模式）

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--resolution` | `1K|2K|3K|4K` | — |  | — | — |
| `--aspect` | `16:9|1:1|21:9|2:3|3:2|3:4|4:3|9:16` | — |  | — | — |

### 渲染

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--light-level` | `0|~|1|2` | — | 光照档位（0~12），按时间自动分类的等级；显式给出可覆盖自动判定。 | --time/--weather 先算，再被本项覆盖 | `--light-level 6` |
| `--wall-desc` | bool | — | 墙面材质描述（自然语言），只影响 AI 生成阶段的提示词。 | 仅 --ai 生效；离线模式无效 | `--wall-desc "斑驳的老水泥墙"` |
| `--ssaa` | int | — | 超采样倍数（1=关，越大越慢越干净）。 | 耗时与倍率近似平方关系，4K 建议 <=2 | `--ssaa 2` |
| `--seed` | int | — | 随机种子（固定后噪声/纹理可复现）。 | 配合 --no-render/--show-config 做可复现实验 | `--seed 12345` |

### 物理参数

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--cinnabar` | float | — | 朱砂/主色 RGB（三个 0~255 整数），覆盖默认色。 | nargs=3；影响材质基色与光照耦合结果 | `--cinnabar 180 40 30` |
| `--noise-low` | float | — | 低频噪声强度（大尺度起伏）。 | 与 --noise-mid/--noise-high 成组 | `--noise-low 0.4` |
| `--noise-mid` | float | — | 中频噪声强度（主颗粒感）。 | — | `--noise-mid 0.5` |
| `--noise-high` | float | — | 高频噪声强度（细砂感）。 | — | `--noise-high 0.3` |
| `--diffusion` | float | — | 光扩散/柔化强度。 | 越大阴影越软 | `--diffusion 1.2` |
| `--oxidation` | float | — | 氧化/做旧程度。 | — | `--oxidation 0.35` |
| `--shadow-strength` | float | — | 阴影浓度（0=无影）。 | 与 --light-level 一起决定画面明暗结构 | `--shadow-strength 0.8` |
| `--material-coupling` | float | — | 字形随墙面材质起伏的耦合强度（0=关闭）。 | 值越大字越「融进」墙里 | `--material-coupling 0.6` |
| `--exposure` | float | — | 画面曝光倍率（>1 更亮）。 | 后期参数，不改变照明计算 | `--exposure 1.15` |
| `--saturation` | float | — | 画面饱和度倍率（1=原始）。 | — | `--saturation 0.9` |

### 控制

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--token` | bool | — | AI 服务令牌（仅 --ai 模式需要）。 | 也可用环境变量 AGNES_API_TOKEN，或先写进配置 | `--token "xxx"` |
| `--settings` | （开关） | False | 打开设置面板（交互式）。 | 非交互终端会退化 | `--settings` |
| `--no-color` | （开关） | False | 关闭 ANSI 颜色（日志更易被程序解析）。 | 等价环境变量 NO_COLOR=1；AI/CI 调用建议总是加 | `--no-color` |
| `--yes` | （开关） | False |  | — | — |
| `--verbose` | （开关） | False |  | — | — |
| `--log-level` | DEBUG/INFO/WARN/ERROR | — | 日志级别。 | 覆盖 -v 的默认级别 | `--log-level DEBUG` |
| `--log-file` | （开关） | False | 把日志写入文件（默认 output/ 下）。 | 配合 -v 便于事后排错 | `--log-file` |
| `--dry-run` | （开关） | False | 演练：解析参数与配置，但不真正渲染/请求。 | 用于排查参数；exit 0 不代表渲染可用 | `--dry-run` |
| `--no-render` | （开关） | False | 只做前置步骤（如生成/光照底图），跳过最终叠字与渲染。 | 配合 --keep-lit 得到中间产物 | `--no-render --keep-lit` |

### 查询

| 参数 | 取值 | 默认 | 语义 | 交互/注意 | 示例 |
|---|---|---|---|---|---|
| `--list-fonts` | （开关） | False | 列出可用字体（名 → 路径）。 | 只读查询，exit 0 | `--list-fonts --no-color` |
| `--list-backgrounds` | （开关） | False | 列出内置底图名。 | 只读查询 | `--list-backgrounds --no-color` |
| `--list-ntp` | （开关） | False | 列出内置 NTP 服务器。 | 只读查询 | `--list-ntp` |
| `--list-services` | （开关） | False | 列出内置 IP 定位服务。 | 只读查询 | `--list-services` |
| `--list-sizes` | （开关） | False | 列出 (档位, 纵横比) → 像素 的完整映射。 | 选 -r/-a 前查这里 | `--list-sizes` |
| `--show-config` | （开关） | False | 打印当前生效配置（含来源）。 | 排错首选 | `--show-config` |
| `--reset-config` | （开关） | False | 恢复出厂配置。 | 会写配置文件（破坏性）；建议先 --show-config 备份 | `--reset-config` |
| `--version` | （开关） | ==SUPPRESS== | 打印版本号后退出。 | argparse 内建 action=version | `--version` |

## 6. 现成命令（可直接复制）

- **最小可用（离线，无需网络/坐标）**

  ```bash
  agnes-render --offline-bg 微水泥 -t "字" -y --no-color
  ```
- **确定性输出路径（推荐给自动化）**

  ```bash
  agnes-render --offline-bg 微水泥 -t "字" -o /tmp/out --output-name cover -y --no-color
  ```
- **指定时间 + 坐标 + 天气（物理光照最准）**

  ```bash
  agnes-render --offline-bg 微水泥 --time "2024-06-21 12:00" --lat 39.9042 --lon 116.4074 --weather clear -t "字" -y
  ```
- **固定随机种子做可复现实验**

  ```bash
  agnes-render --offline-bg 微水泥 --seed 12345 --ssaa 1 -t "字" -y
  ```
- **只出光照底图（中间产物）**

  ```bash
  agnes-render --offline-bg 微水泥 --keep-lit --no-render -y
  ```
- **列出可用资源（机器可解析）**

  ```bash
  agnes-render --list-fonts --list-backgrounds --no-color
  ```
- **写定位缓存，后续 --gps 一键用**

  ```bash
  agnes-render --set-location "39.9042,116.4074,北京"
  ```
- **CI/容器里跑（无 TTY、无 locale）**

  ```bash
  LC_ALL=C NO_COLOR=1 agnes-render --offline-bg 微水泥 -t "字" -y --no-color
  ```
- **Android/Termux 嵌入调用**

  ```bash
  agnes-render --offline-bg 微水泥 -o /sdcard/Pictures -y --no-color   # 坐标用 --lat/--lon 或 --set-location
  ```

## 7. 报错 → 原因 → 处理

| 现象 | 原因 | 处理 |
|---|---|---|
| exit=2 且没有输出 | 参数名拼错 / choices 越界 | agnes-render --help；或核对本文档的取值列 |
| 提示「未在 background/ 找到底图」 | 底图名不对或素材目录不在便携根 | agnes-render --list-backgrounds；必要时设 OWNRENDER_HOME |
| 「需要 --token 或配置」 | --ai 模式没给令牌 | --token 或 export AGNES_API_TOKEN，或改用 --offline-bg / -i |
| 「位置解析失败」 | 定位链全失败（无 GPS、无网、无坐标） | 直接 --lat/--lon，或先 --set-location 写缓存 |
| 等很久没有输出 | 非交互环境里在等确认 | 加 -y |
| 颜色转义污染日志 | ANSI 颜色 | --no-color 或 NO_COLOR=1 |
| 容器里中文报编码错 | locale 不是 UTF-8 | LC_ALL=C 也能跑（已验证）；或设 PYTHONUTF8=1 |
| ImportError: libblas/libgfortran/libjpeg... | 下载的二进制包缺系统库（打包问题） | 重新下载最新 Release；打包脚本会用 DT_NEEDED 自动补系统库 |

## 8. 取值枚举（程序可直接用）

- `resolution`: `1K`, `2K`, `3K`, `4K`
- `aspect`: `1:1`, `3:4`, `4:3`, `16:9`, `9:16`, `2:3`, `3:2`, `21:9`
- `anchor`: `center`, `tl`, `tr`, `bl`, `br`, `tc`, `bc`, `lc`, `rc`
- `window_orientation`: `left`, `right`, `n`, `ne`, `e`, `se`, `s`, `sw`, `w`, `nw`
- `weather`: `auto`, `clear`, `cloudy`, `overcast`, `rain`, `snow`, `haze`
- `font_ext`: `.otc`, `.otf`, `.ttc`, `.ttf`, `.woff`, `.woff2`
- `image_ext`: `.bmp`, `.jpeg`, `.jpg`, `.png`, `.webp`

