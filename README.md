# OwnRender

**面向「墙面 + 窗光」的物理光照渲染引擎** —— 把一张平光材质贴图，按真实天文与
光学模型重新打光，并在墙面上叠印一段有年代感的文字。

> English: [README.en.md](README.en.md) · 文档导航见 [docs/](docs/README.md)

---

## 它做什么

输入：一张**均匀平光**的墙面材质图 + 一句话。
输出：一张**有真实窗格光斑、随时间/天气/朝向变化**的成图，墙面上叠着朱红题字。

光照不是"滤镜"：太阳与月亮的位置由经纬度与 UTC 时刻算出，大气透过率按
Rayleigh/Mie 散射分波长计算，室内墙体由光线追踪得到，最后经 ACES 色调映射与
相机效果编码为 sRGB。

```
底图(平光) ─► Retinex 分解 ─► PBR 材质提取 ─► 3D 场景 + 光线追踪
          ─► ACES 色调映射 ─► 相机效果 ─► 曝光/饱和 ─► sRGB 成图
          ─► 文字 SSAA ─► 年代感 ─► 接触阴影 ─► 物理光学合成
```

---

## 特性

- **真实天文**：太阳/月亮方位与高度、日出日落、暮光、月相与月光亮度
- **分波长大气**：`T(λ)=exp(-(τ_R(λ)+τ_M)·AM)`，低太阳角自动偏橙红
- **天光漫射**：即使无直射光，室内仍随时间/云量正确变亮变暗（不是死黑）
- **窗格光斑**：位置/拉伸/剪切由太阳方位角与高度角驱动，支持半影软化
- **窗户几何**：朝向（东/西）、尺寸、窗格行列、窗框占比、阴影倍率
- **天气系统**：7 种预设 + 云量/降水/能见度/湿度全手动，含**实时效果预测**
- **跨环境定位**：Termux / Android / Linux(GeoClue/gpsd/ModemManager) /
  macOS / Windows / 时区兜底 / IP 定位 / 本地缓存
- **文字渲染**：SSAA 抗锯齿、标点智能断行、朱红颜料物理合成、
  接触阴影、多层噪声年代感、材质耦合（可选）
- **纯本地**：除可选的 AI 生成与大模型无关的接口外，渲染全程离线、无外部依赖

---

## 环境要求与预装库

| 项 | 要求 |
|---|---|
| Python | 3.9+（开发环境 3.12） |
| 依赖库 | **numpy**、**Pillow**、**requests** |
| 可选 | `uv`（极快的包管理器） |
| 平台 | Linux / macOS / Windows / Termux / Android(proot) |

> 只有 3 个第三方库。`requests` 仅用于可选的 AI 生成、NTP、定位与天气查询；
> **纯离线光照 + 叠字不需要联网**。

安装：

```bash
pip install numpy Pillow requests
# 或用 uv（推荐）
uv venv && uv pip install numpy Pillow requests
```

详见 [docs/依赖与安装.md](docs/依赖与安装.md)。

---

## 快速开始

```bash
python main.py
```

进入 TUI 主菜单：

```
┌──────────────────────────────────────────────────────────────────────────┐
│  agnes-render  ·  物理光照墙面渲染                                        │
│  v10.0.0   底图 16 张   字体 3 个   模式 AI / 离线 / 自定义                 │
└──────────────────────────────────────────────────────────────────────────┘
  主菜单
     [0] AI 生成底图 + 叠字          （在线，需要 Token）
   ▸ [1] 内置底图 + 物理光照 + 叠字   （离线）
     [2] 自定义图片 + 叠字            （离线，不光照）
     [3] 设置
     [4] 信息 / 环境自检
     [5] 退出
     回车=1     a/b/c/s/i/q 快捷选择
```

选择模式后进入**参数向导**：所有步骤一次列出，**可反复跳回任意一步修改**，
确认后才开始渲染。

```
   [0] 文字      谎如昨日， / 嗤笑今朝
   [1] 字体      AaXiuKai-2.ttf
   [2] 排版      比例0.18 center (50,50) SSAA8
   [3] 底图      微水泥.png
   [4] 时间      此刻 06-21 12:00 (UTC+8)
   [5] 位置      北京 (39.90,116.41)
   [6] 天气      clear
   [7] 光照      right 窗格3x2 阴影auto
   [8] 渲染      SSAA8 seed=None
   [9] 年代感    耦合0 扩散0.2 阴影0.25
   [10] 画面     曝光1 饱和1
   [11] 输出     ./output
 ▸ [12] ✓ 开始生成        [13] 放弃
```

---

## 三种模式

| 模式 | 输入 | 光照 | 联网 |
|---|---|---|---|
| **AI 生成** `--ai` | 提示词 + Token | 由 AI 按光照描述直接生成（不做光线追踪） | 需要 |
| **离线光照** `--offline-bg NAME` | `background/` 里的材质图 | **光线追踪物理光照** | 不需要 |
| **自定义** `-i PATH` | 任意图片 | 不做光照，只叠字 | 不需要 |

---

## 命令行

```bash
# 最简：离线光照 + 叠字（用默认底图、当前时间与位置）
python main.py --offline-bg 微水泥 -y

# 指定时间/位置/天气（--time 支持带时区偏移，无歧义）
python main.py --offline-bg 微水泥 \
    --time "2025-06-21T12:00:00+08:00" \
    --lat 39.9042 --lon 116.4074 \
    --weather clear -y

# 手动微调天气：多云 + 30% 云量 + 能见度 10km
python main.py --offline-bg 青砖墙 --weather cloudy \
    --cloud 30 --visibility 10000 --humidity 55 -y

# 自定义图片只叠字
python main.py -i ./my_wall.png -t "谎如昨日，嗤笑今朝" -y

# 画面微调 + 年代感
python main.py --offline-bg 锈蚀钢板 --exposure 1.15 --saturation 0.9 \
    --material-coupling 0.4 --diffusion 0.25 -y

# 查询类
python main.py --list-backgrounds     # 列出底图
python main.py --list-fonts           # 列出字体
python main.py --show-config          # 查看当前配置
python main.py --help                 # 全部参数
```

完整参数表见 **[docs/命令行参数.md](docs/命令行参数.md)**。

---

## 素材

- `background/` —— **16 张平光材质底图**（微水泥、粗灰泥、红砖、清水混凝土、
  大理石、瓷砖、木饰面、锈蚀钢板、青砖…）。生成参数与提示词见
  [background/README.md](background/README.md)。
- `fonts/` —— 3 款中文字体。**来源于网络，仅限非商业学习使用，侵删**，
  详见 [CREDITS.md](CREDITS.md) 与 [fonts/README.md](fonts/README.md)。

> 想换成自己的素材：把图片放进 `background/`、字体放进 `fonts/` 即可，
> 程序会自动识别（支持 png/jpg/jpeg/webp/bmp 与 ttf/otf/ttc/otc/woff/woff2）。

---

## 可能的效果

以下为不同参数下的典型表现（**本仓库不附带任何生成结果**，请自行渲染验证）：

| 场景 | 设置 | 预期画面 |
|---|---|---|
| 正午晴 | `--time …12:00 --weather clear`，窗朝东 | 直射很弱（太阳近窗平面），墙面**由天光均匀照亮**，偏冷白 |
| 上午晴 | `--time …09:00 --weather clear` | 墙面出现**清晰的窗格状光斑**，边界锐利，位置偏一侧 |
| 黄昏 | `--time …18:30`，窗朝西 | 光斑**拉长、偏橙红**，低角度长阴影 |
| 深夜 | `--time …23:00` | 极暗蓝调；有月光时为冷蓝白弱光斑 |
| 阴天 / 雾 | `--weather overcast/haze` | 光斑**边界明显变软**甚至消失，整体低对比 |
| 雨天 | `--weather rain` | 光斑模糊 + 墙面叠加**水痕**质感 |
| 雪天 | `--weather snow` | 叠加**雪花亮点**，整体色温偏冷 |
| 叠字（默认） | 朱红颜料 | 文字呈**哑光朱红**，吃进墙面纹理，带轻微氧化颗粒 |
| 叠字（年代感强） | `--noise-low 0.3 --diffusion 0.4 --oxidation 0.5` | 文字更**斑驳、边缘发毛**，像旧标语 |
| 叠字（清晰） | `--noise-low 0.05 --diffusion 0.1 --oxidation 0` | 文字**干净锐利**，接近现代印刷 |

更多说明见 [docs/效果与样例.md](docs/效果与样例.md)。

---

## 目录结构

```
OwnRender/
├── main.py                 入口（初始化配置 → 交给交互层）
├── config.py               配置层：常量 / 读写 / 字体与断行辅助
├── frame_light/            光照子框架
│   ├── astro.py            天文：日月位置、大气散射、天气、定位 provider
│   ├── light.py            光照主入口：compute_light
│   ├── geometry.py         窗格几何：光斑位置/形状/半影/阴影
│   ├── scene3d.py          3D 房间与相机
│   ├── raytrace.py         光线追踪 + 环境光
│   └── scene.py            场景光构成
├── frame_render/           渲染子框架
│   ├── pipeline.py         编排：Retinex → 材质 → 追踪 → ACES → 相机
│   ├── retinex.py          光照/反射率分解
│   ├── material.py         PBR 材质提取
│   ├── text.py             文字 SSAA / 年代感 / 接触阴影 / 合成
│   ├── compose.py          编码
│   └── utils.py            色彩空间与数学
├── frame_interact/         交互子框架（TUI）
│   ├── tui.py              TUI 工具箱（颜色/菜单/输入/向导）
│   ├── wizard.py           参数向导（天气/字体/底图/材质耦合…）
│   ├── settings.py         设置中心
│   ├── runner.py           主菜单与分发
│   ├── cli.py              命令行参数
│   └── offline.py / ai.py  两种模式的编排
├── background/             材质底图
├── fonts/                  字体
├── tools/                  辅助脚本
└── docs/                   文档（中文 / English）
```

---

## 文档

分三级，见 **[docs/README.md](docs/README.md)**

- **入门**：[快速开始](docs/快速开始.md) · [依赖与安装](docs/依赖与安装.md)
- **进阶**：[配置说明](docs/配置说明.md) · [效果与样例](docs/效果与样例.md)
- **参考**：[命令行参数](docs/命令行参数.md) · [架构](docs/架构.md) · [FAQ](docs/FAQ.md)
- **English**：[docs/en/](docs/en/index.md)

---

## 许可

**GNU Affero General Public License v3.0（AGPL-3.0）** —— 全文见 [LICENSE](LICENSE)

```
Copyright (C) 2025 yingo-server and OwnRender contributors
```

- ✅ 可自由使用、修改、分发，**包括商业使用**
- 🔁 **衍生作品必须开源**：分发二进制或源码，以及**通过网络向用户提供服务**时，
  都必须按 AGPL-3.0 向接收者提供完整对应源码，并以同一协议授权（AGPL §13 网络条款）
- 🧾 **无担保**：本软件按"原样"提供，作者不承担任何担保与责任（AGPL §15–§17）
- 💼 如果你的场景**无法接受 AGPL 的开源义务**（例如闭源产品内嵌、闭源 SaaS），
  可联系作者洽谈**商业授权**（双授权）
- ⚠️ `fonts/` 与 `background/` 中的第三方素材**不属于代码许可的覆盖范围**，
  各有其自身条款，见 [CREDITS.md](CREDITS.md)

素材侵权申诉（[DMCA]）或商业授权：请提交 **Issue**。

> 📌 程序内部与命令行仍沿用历史名 `agnes-render`（启动横幅、`--help` 的 prog 名），
> 与仓库名 OwnRender 是同一个项目。

<!-- binaries-link -->
---

📦 **二进制包**（Windows / Linux / macOS / Android `.so`，由 CI 用 Nuitka 自动构建）—— **下载与使用方式 → [docs/二进制包.md](docs/二进制包.md)**
