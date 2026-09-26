# agent.md — OwnRender 重构总纲（V11 / 3D 物理渲染）

> 本文件是**项目宪法**。任何 AI/人动这个仓库之前先读它；
> 与本文冲突的实现一律视为 bug。改动前先备份，改完必须自测。

---

## 0. 给 AI 的铁律（先读这 10 条）

1. **参数必须真实**：能用物理关系/公开经验式算出来的，绝不写手调表；
   能用几何算出来的（面积、距离、夹角），绝不拍系数。
2. **全局手调参数 ≤ 5 个**，且每个都要注明出处；由自测强制守门。
   材料常数（反照率/折射率/粗糙度）不计入手调，但必须标"材料属性"。
3. **"显示异常"≈"参数没对接"**：先把数据流捋直（API/图像/几何里已有的量
   有没有进计算），再谈算法。不许用"调参"掩盖"缺项"。
4. **不许硬凑**：算出来该很小就让它很小（例：室内空气光只有百分之几），
   为了"好看"放大物理量 = 制造下一个 bug。
5. **可复现**：任何随机性必须由确定性种子驱动（同输入必同输出），
   因为要断点续跑 / 批量 / 缓存 / CI 出图。
6. **缓存优先**：同一个底图/同一套参数不许重复计算（见 §8）。
7. **只写逻辑与算法**：通用能力（TUI 渲染、编码探测、图像编解码、几何 IO、
   视频封装）一律用成熟第三方库，别自己造。
8. **不改"叠字"子系统的成熟算法**（见 §9），只能通过接口喂它。
9. 每次改动：`tools/selftest.py` 必须全绿；新增物理量必须补守门测试。
10. 打 tag / 发 Release 前，`docs/*.md` 与 `tools/gen_cli_doc.py` 生成物必须一致。

---

## 1. 备份

- 已备份：`/sdcard/render_backup_20260926_1143.tar.gz`（37MB / 89 项，
  含源码、docs、`.github/workflows`；排除 dist/output/__pycache__）。
- 规则：**任何大规模重构前再打一次快照**，命名 `render_backup_YYYYmmdd_HHMM.tar.gz`。
- 三份工作副本互为镜像：`/sdcard/render`（主）、`/root/OwnRender`、`/sdcard/render_stage/OwnRender`。

---

## 2. 为什么必须重构（实测证据，不是感觉）

| 问题 | 证据 | 根因 |
|---|---|---|
| 动态范围塌缩 | 阴/雨/雪整图挤在 0.22~0.44 | 环境光是**全图常数** |
| 天气彼此不可分 | 雪天与阴天**逐位相同**；雪比晴暗 2.4 倍 | 云被当成 Mie 气溶胶；缺地面反弹 |
| 夜间是死帧 | 00:00 与 04:00 逐像素相同 | 夜间环境光是常数 |
| 正午出现不该有的光斑 | 太阳方位 177.8°、窗朝东、入射角差 88° | **缺窗户 Lambert 入射余弦**（只判二元可见性） |
| 照度场是"径向光晕" | 字符图显示以窗心为圆心、上下镜像 | 把窗户当**点光源** |
| 房间不被整体照亮 | 靠窗亮、远处暗到过低 | 缺**室内多次互反射**项 |
| 空文案变成别人的示例句 | `-t ''` 渲染出「谎如昨日，嗤笑今朝」 | `pick_text()` 兜底写了示例句 |
| 光照只有二维 | 只有"一面墙 + 光斑 mask" | 架构本身是 2D 拼接 |

**结论**：不是某一处算法错，而是**架构维度不够**——必须把"墙"升级成"房间"，
让光在真实的 3D 几何里传播。

---

## 3. 目标架构

### 3.1 分层（单向依赖，禁止反向 import）

```
ownrender/
├── core/            纯数学与色彩：色彩空间、色调映射、噪声、球面几何、单位
├── scene3d/         3D 场景：几何（房间/墙/开口）、材质、相机、splat 缓存
├── light/           光源与大气：太阳(面光源)、天空穹顶、地面、月亮/星辉、天气
├── transport/       光传输：直接光 / 天空积分 / 互反射(辐射度) / 可选路径追踪
├── surface/         材质表现：BRDF(漫反射/GGX镜面/湿面/雪)、裂缝/污渍、
│                    年代感纹理、镜面反射的特殊处理
├── textoverlay/     叠字子系统（**保留现有成熟算法**，只做接口化）
├── pipeline/        编排：场景→光源→传输→成像→叠字→输出；缓存与批处理
├── interact/        CLI / TUI / 配置向导（库：typer + textual + rich）
└── tools/           批处理脚本、参数文档生成、自测、CI 辅助
```

依赖方向：`core ← scene3d ← light ← transport ← surface ← pipeline ← interact`
（`textoverlay` 只依赖 `core`+`surface` 的纹理图，保持独立可测）。

### 3.2 数据流

```
底图(JPG/PNG) ──sha256──► 建模缓存(§8) ──► 房间几何 + 材质图
                                                   │
系统时间/地理位置/天气(API 或预设) ──► 太阳方向·角直径·光谱 ──► 光源集
                                                   │
                                    transport（直接光 + 天空积分 + 互反射）
                                                   │
                              相机（虚拟机身：快门/曝光适应/传感器）
                                                   │
                                         成像（线性 HDR 图）
                                                   │
                                   textoverlay（年代感 + 墨水浓度 + 接触阴影）
                                                   │
                                          输出 PNG/JPG / 批量 / 视频
```

### 3.3 批量优先（从底座就支持）

- 一次进程可渲染 N 张（时间序列 / 参数扫描 / 多底图），**场景只建一次**；
- 场景/材质/几何缓存复用（§8）；
- 进程内并行（`concurrent.futures`）+ 错峰启动（避免同时抢 CPU）；
- 断点续跑：每帧产物按 `帧号+参数哈希` 命名，已存在则跳过；
- 进度与失败清单落盘（`progress.json` / `timeline.tsv`）。

### 3.4 技术栈（只写逻辑，其余交给库）

| 用途 | 选型 | 理由 |
|---|---|---|
| 数值 | `numpy`（+`scipy.sparse` 做互反射矩阵） | 既有的数值底座 |
| 图像 IO/绘制 | `Pillow`（+`imageio` 备选） | 字体/解码/格式全 |
| 图像分析 | `opencv-python`（裂缝/边缘/形态学），`scikit-image` 备选 | 裂缝检测不能自己造 |
| 几何 | `trimesh`（网格/交点/法线） | 房间几何与法线运算 |
| 3DGS（后期） | `gsplat` 或 `plyfile`+自写光栅 | B 阶段再引入 |
| CLI | `typer`（+`click` 兜底） | 参数文档可自动生成 |
| TUI | `textual` + `rich`（LOGO 用 `pyfiglet`/`art`） | **不自己写 TUI** |
| 配置 | `pydantic`（校验）+ JSON 落盘 | 参数越界早失败 |
| 日志 | `loguru`（`--no-color` 走纯文本） | 结构化 + 彩色 |
| 编码/多终端 | `charset-normalizer` + `wcwidth` + `colorama` | **多终端/多语言支持交给库** |
| 视频 | `imageio-ffmpeg`（自带 ffmpeg） | 免装系统 ffmpeg |
| 测试 | `pytest`（+ 现有 `tools/selftest.py` 守门） | 商业项目基线 |

> 打包：仍用 Nuitka standalone（现有 CI 已跑通 7 平台验收）。

### 3.5 第三方库边界（细化到功能级）★

**原则：凡是"通用能力"（交互、渲染、编解码、IO、几何容器、视频封装），一律用成熟库；
我们只写"本项目的物理与算法"。** 下表是硬性分工，新增功能先查表，找不到再讨论。

| 功能 | 交给库 | 我们只写 |
|---|---|---|
| 命令行解析/子命令/帮助 | `typer`（底层 `click`） | 参数语义与校验规则 |
| TUI 布局/滚动/键鼠/窗口 | `textual` | 状态机与业务动作 |
| 终端着色/表格/进度条 | `rich`（`Progress`/`Table`/`Panel`） | 展示哪些量 |
| TUI LOGO/艺术字 | `pyfiglet` / `art` | 无 |
| 配置定义/校验/环境变量 | `pydantic`（+`pydantic-settings`） | 参数取值范围与物理约束 |
| 日志 | `loguru`（`--no-color` 纯文本后端） | 日志字段（物理量） |
| 编码探测（UTF-8/GBK/CP936…） | `charset-normalizer` | 无 |
| 宽字符/多语言对齐（CJK 罗马字） | `wcwidth` | 无 |
| 图像读写/缩放/高质量重采样 | `Pillow`、`imageio` | 颜色空间与线性化 |
| 图像分析（裂缝/污渍/边缘/形态学） | `opencv-python-headless`、`scikit-image` | **裂缝判定规则**与光渗模型 |
| 网格/射线相交/法线的通用容器 | `trimesh`（可选） | 房间拓扑、开口、能量公式 |
| 稀疏线性求解（互反射） | `scipy.sparse.linalg` | 形状因子 `F` 与辐射度方程 |
| 视频封装（mp4/gif） | `imageio-ffmpeg` | 帧序、时长、物理时间映射 |
| 3DGS 渲染（B 阶段） | `gsplat`（可选） | 缓存键、房间材质映射 |
| HTTP/NTP | `requests`（+`ntplib` 备选） | 数据→物理量的映射 |
| 测试 | `pytest`（CI） | 物理守门断言（单调/守恒/有界） |
| 打包 | `Nuitka`（现有 CI） | 资源与版本注入 |

**反面清单（禁止自己实现）**：TUI 控件、ANSI 转义、表格排版、进度动画、
JSON/YAML 解析、图像编解码、PNG 元数据、mp4 封装、稀疏矩阵求解、
Unicode 宽度、正则方言、日志轮转。

**可选依赖必须软降级**：`opencv`/`trimesh`/`scipy`/`gsplat` 缺失时，
功能降级（例如裂缝检测退化为"不做"）但**程序必须照常出图**，并在日志里说明。

---

## 3.6 模块职责细化（每个文件干什么）

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `core/color.py` | sRGB↔线性、色温→RGB、光谱加权 | `srgb_to_linear`, `cct_to_rgb` |
| `core/tonemap.py` | ACES/Reinhard、曝光适应（Stevens） | `tonemap(x, gain)`, `eye_ev(E, alt)` |
| `core/geometry.py` | 球面/平面几何、投影立体角、射线-矩形 | `projected_solid_angle(...)` |
| `scene3d/room.py` | 房间 6 面 + 开口、材质、校验 | `Room.from_config`, `Room.validate`, `irradiance_from_opening` |
| `scene3d/cache.py` | **建模缓存**（sha256+md5）、读写 npz/json | `model_key`, `save_model`, `load_model` |
| `light/sun.py` | 太阳=面光源（角直径、半影、圆盘采样） ✅已实现 | `penumbra_width_m`, `disc_samples` |
| `light/sky.py` | **天空=穹顶**：CIE 辐射分布 + 等立体角离散 | `dome_samples`, `dome_radiance`, `through_opening` |
| `light/weather.py` | 天气物理量→直射/漫射/湿面/地面状态 | `derive(...)`（现 `atmosphere.py` 迁移） |
| `light/geo.py` | 经纬度/海拔/时区→太阳位置与角速度 | `sun_position`, `angular_speed` |
| `transport/direct.py` | 直接光（含窗户余弦 + 半影卷积） | `direct_irradiance(P, n, sun, opening)` |
| `transport/skyint.py` | 天空透过开口的积分（**面光源**） | `sky_irradiance(P, n, sky, opening)` |
| `transport/radiosity.py` | 互反射（形状因子 + 稀疏解） | `solve_radiosity(room, E)` |
| `surface/cracks.py` | 裂缝检测（opencv）+ 光渗 | `detect_cracks(img)`, `apply_seep(...)` |
| `surface/brdf.py` | 漫反射/GGX/湿面/雪/镜面 | `eval_brdf(...)` |
| `surface/mirror.py` | 镜面单次弹射 + **禁 6 镜面** | `mirror_bounce(...)`, `validate_specular(room)` |
| `textoverlay/` | 移植现有叠字（不改算法），加 `ink_density`/`pigment` | `overlay(img, text, params, light)` |
| `pipeline/render.py` | 场景→光源→传输→成像→叠字 | `render_one(spec)`, `render_batch(specs)` |
| `pipeline/cache.py` | 帧级缓存与断点续跑 | `frame_path(spec)`, `is_done(spec)` |
| `interact/cli.py` | typer 命令面 + 参数文档生成 | `app`, `--dump-args-json` |
| `interact/tui.py` | textual 界面（LOGO 用 pyfiglet） | `OwnRenderApp` |

---

## 4. 光源模型（重构的核心之一）

### 4.1 太阳 = **面光源（视直径 ≈ 0.53°）**，不是点光源

- 太阳有角直径 ⇒ 本影/半影：
  `半影宽度 ≈ 光斑距离 × tan(0.265°) ≈ 距离 × 0.0046`
  距离越远 → 边缘越软；**这就是"一天里光斑有时清晰、有时模糊"的物理来源**。
- 太阳辐照度随高度的变化已有（Rayleigh/Mie 透过率）⇒ 强度与色温。
- 太阳光谱：`astro.solar_irradiance_rgb()`（分波长）已具备，继续用。
- 临边昏暗（limb darkening）可选：低角时更明显。

### 4.2 天空 = **穹顶光源（半球，四面八方）**

**这是之前最大的错误**：天空被当成"窗户那么大的一块"。
正确做法：
- 天空按半球面离散化（例：方位 36 × 仰角 9 ≈ 324 个天元），每元给辐射亮度 `L_sky(θ,φ)`；
- 过曝天气：`L_sky` 更均匀、整体更亮（overcast 的**辐射亮度**可以接近甚至高于晴空的某些方位）；
- 晴空：`L_sky` 有 Rayleigh 梯度（天顶冷蓝、地平线亮暖）→ 用 `astro.sky_color()` 扩展成分布；
- 房间照度 = 对**天空可见的那部分**（透过开口）做投影立体角积分；
- 与"点源近似"的区别：窗户只是**开口**，但光源是整个穹顶，因此
  **照度场是缓慢下降的软场，且几乎铺满整个房间**（配合 §5 互反射）。

### 4.3 地面 / 环境 / 夜间

- 室外地面：反照率按状态（雪 0.80 / 湿 0.07 / 干 0.25），参与互反射；
- 夜间：月亮（视直径同太阳，按相位给辐照度）+ 星空/城市辉光（天顶亮度梯度）；
- 城市光害可按雾/云散射增强（可选）。

---

## 5. 光传输

1. **直接光**：太阳方向 × 窗户入射余弦 × 可见性（本影/半影按 §4.1 用角直径卷积）；
2. **天空直入**：§4.2 的穹顶积分（透过开口）；
3. **互反射（辐射度）**：房间 6 面离散成小片（例：每面 12×12），
   解 `B = E + ρ·F·B` 一次（稀疏线性系统，几毫秒）。
   **这是"房间整体被照亮"的来源**，替换现在那个 k=ρ/(1-ρ) 的近似；
4. **可选路径追踪**：`--pt` 开关，给需要极致质量的场景（反射/焦散）。

---

## 6. 大气 / 天气 / 地理

- **地理**：经纬度 → 太阳方位/高度；**纬度还决定太阳角速度与日轨倾角**
  （高纬度斜日轨、低纬度陡日轨）；海拔 → 大气质量修正；时区/夏令时 → 本地时刻映射。
- **时间**：影响入射角、强度、色温、太阳角速度，**也影响云的时空演化**（阵雨）。
- **天气物理量必须全接**：`cloud` 云量、`precip` 降水、`temp` 气温、
  `vis` 能见度、`humidity` 湿度、`code` WMO 码。
- **水分/折射/色散**（用户点名的细节）：
  - 水汽柱 → 透过率与色温微调；
  - 雨幕/雾滴 → Mie 散射（体散射近似：`β=3.912/vis`）；
  - 色散：大气折射率随波长变化 → 低角太阳的色分离（蓝更衰减）已部分实现，
    需把 `n(λ)` 参与折射/地平线压缩（可选高阶）；
  - 湿面镜面反射增强、雪面多次散射增亮。
- 直射/漫射分离：覆盖加权云透过率 + 云修正因子 + 能量守恒（已实现，保留）。

---

## 7. 场景与材质

- **房间**：6 个面 + 开口（窗/门）；每面给 `albedo / roughness / metallic|specular / IOR`；
- **镜面要额外处理**（用户点名）：
  - 镜面面用反射光线再采样一次场景（单次弹射即可），
  - **禁止"6 面全镜面"**：物理上不可能（无像的共同可见性），配置校验里直接拒绝；
  - 镜面上叠字：文字本身在镜面里**可见**（算法要支持"文字的镜像视图"，
    而不是简单贴图），因为镜面反射的是"含字的场景"。
- **裂缝 / 污渍自动检测**：
  - 用 OpenCV：黑帽/形态学骨架/Canny + Hessian 线检测 → 裂缝掩膜；
  - 裂缝参与"光线内渗（凹处变暗）"与年代感纹理；
  - 大块污渍用低频 Retinex 残差提取（已有 `analyze_wall_material` 可复用）。
- 材质提取（PBR 五通道）保留现有 `frame_render/material.py` 思路，迁移到 `surface/`。

---

## 8. 缓存与批量（不重复泼溅房间）

- **建模缓存键** = `sha256(底图字节)` + `md5(几何/材质参数)` + `版本号`；
- 缓存内容：房间几何、每面材质图（albedo/roughness/specular/height）、
  裂缝掩膜、年代感噪声纹理、互反射矩阵；
- 存储：`~/.cache/ownrender/models/<key>/`（可移植：`OWNRENDER_HOME` 覆盖）；
- **命中即跳过建模**（秒级 vs 分钟级）；
- 帧缓存：`out/frames/<参数哈希>/f0000.png`，存在即跳过（断点续跑）；
- 体积控制：材质图按需下采样存储 + `npz` 压缩。

---

## 9. 叠字子系统（保留成熟算法，只做接口化）

**不改算法**，只把输入输出约定清楚：

```
overlay(text, font, ink_params, light, surface_maps) -> RGBA
```
- 现有能力保留：SSAA 文字 alpha、年代感（氧化颗粒/边缘侵蚀/颜料扩散）、
  接触阴影、材质耦合；
- **新增暴露的参数**（用户点名）：
  - `ink_density`（墨水浓度：影响 alpha 峰值与边缘渗色）
  - `aging`（年代感强度 0~1，已有 `aged_*` 参数）
  - `pigment`（颜料反射率：已有 `CINNABAR_REFLECTANCE`，可切朱砂/墨/金）
- 叠字发生在**成像之后**（z 空间）而不是光照里——但接触阴影需要 `light`。

---

## 10. 目录结构（目标）

```
ownrender/
├── agent.md                  ← 本文
├── README.md  LICENSE  CREDITS.md
├── pyproject.toml            ← 依赖与入口（typer console_scripts）
├── ownrender/
│   ├── core/                 color.py  tonemap.py  noise.py  geometry.py  units.py
│   ├── scene3d/              room.py  opening.py  material.py  camera.py  cache.py  splat.py
│   ├── light/                sun.py  sky.py  ground.py  night.py  weather.py  geo.py
│   ├── transport/            direct.py  skyint.py  radiosity.py  pathtrace.py
│   ├── surface/              brdf.py  cracks.py  stains.py  aging.py  mirror.py
│   ├── textoverlay/          fuse.py  ink.py  shadow.py        （移植现有实现）
│   ├── pipeline/             render.py  batch.py  cache.py  output.py
│   └── interact/             cli.py  tui.py  wizard.py  ui.py
├── tools/                    gen_cli_doc.py  selftest.py  batch_day.py  build_nuitka.py
├── docs/                     参数文档(生成)  物理模型.md  二进制包.md
├── tests/                    test_physics.py  test_cache.py  golden/
└── .github/workflows/        build.yml  verify-release.yml  render-timelapse.yml
```

---

## 11. 参数预算（物理参数：**每个细分方面 ≥15 个**）

**两条规则并存，不要混为一谈：**

| 规则 | 含义 | 守门 |
|---|---|---|
| **风格手调 ≤ 5** | "某种天气=某种亮度/对比度"这类**审美旋钮**永久禁止；仅允许少量工程/数值项（采样数、阈值、并行度） | `tests/test_params.py` 白名单 |
| **每个细分方面 ≥ 15 个物理参数** | 每个方面都要把物理量补全（可测量、有单位、有范围、有出处），宁可参数多而真实，也不要少而拍脑袋 | `tests/test_params.py` 计数 |

**唯一的参数事实源：`ownrender/core/params.py`**（注册表）。
当前 16 个方面、总数见 `docs/参数总表.md`（由 `tools/gen_params_doc.py` 自动生成）：

| 方面 | 内容 |
|---|---|
| `sun` | 方位/高度/视直径/距离/临边昏暗 u1,u2/辐照度/瑞利 τ/气溶胶 τ/臭氧/水汽/Ångström/大气质量/直射比/分波长 |
| `sky` | 天顶亮度/分布模型/阴天梯度/地平线增亮/环日比/浑浊度/漫射照度/穹顶采样/地面回照/色温/星空/辉光/地平线带/偏振 |
| `cloud` | 云量/光学厚度/单次散射反照率/不对称因子/云底高/厚度/LWP/滴径/降水率/阵雨周期/幅度/边缘柔度/分层/种子/温度 |
| `atmos` | AOD/能见度/Koschmieder/气压/气温/湿度/递减率/臭氧吸收/瑞利标高/Ångström β/折射/色散(Abbe)/Mn 因子/MF/透过率/水汽柱 |
| `precip` | 降水率/水膜/饱和率/雪态/地面状态/湿润镜面增益/压暗/雾滴/雨滴/雪花/风速/风向/雨幕倾角/彩虹概率/溅射 |
| `geo` | 经纬度/海拔/时区/夏令时/年积日/赤纬/时角/均时差/**角速度**/昼长/日出日落方位/暮光阈值/**日轨倾角**/地球半径 |
| `room` | 房间尺寸/窗面/窗位/窗宽高/框比/窗格/玻璃透过率与着色/相机位/视场/俯仰 |
| `material` | 反照率(含光谱比)/粗糙度/金属度/F0/折射率/各向异性/法线/置换/清漆/次表面/孔隙率/含水率 |
| `mirror` | 反射率/粗糙度/折射率/镀层/背面镜/着色/倒角/厚度/波纹/浮尘/倾角误差/鬼像/**镜面面上限(禁 6 面)**/弹射/镜中文字可见性 |
| `ground` | 干/湿/雪反照率/粗糙度/雪粒/水膜/坡度/覆盖/植被/建成区/水面/树线/远景辐射/含水/地温 |
| `night` | 月亮高度/方位/相位/辐照度/视直径/色温/夜空辉光/星等限/城市光害方向与强度/钠灯色/气辉线/银河/流星/雪地增益 |
| `transport` | 弹射次数/辐射度分片/形状因子/天空采样/太阳圆盘采样/半影条带/AO 半径与采样/能量容差/通量上限/俄罗斯轮盘/互反射增益/室内反射率/种子/并行度 |
| `camera` | 传感器/像元/焦距/光圈/快门/ISO/曝光/白平衡/黑电平/高光滚降/渐晕/色差/信噪比/衍射/卷帘 |
| `defect` | 裂缝密度/宽度/深度/**光渗**/方向/对比度/检测尺度与阈值/污渍/泛碱/霉斑/起皮/锈斑/浮尘/年代感强度 |
| `ink` | 文案/字号/行距/字距/**墨水浓度**/饱和度/颜料 RGB/笔锋/扩散幅度与半径/边缘侵蚀/氧化颗粒/材质耦合/接触阴影 |
| `color` | 工作空间/位深/色调映射/ACES 增益/S 曲线/视适应 γ/参考照度/饱和/冷偏/暗部青/高光暖/白点/色域截断/抖动/输出格式/JPEG 质量 |

---

## 12. 自测与验收

- **物理守门**（必须单调/守恒/有界）：云透过率、云修正因子、直射漫射分离、
  地面反照率序、水膜饱和、互反射收敛（能量不增）、半影随距离单调变宽、
  镜面能量 ≤ 入射（不造能）、昼夜曝光适应夜间=1。
- **回归**：`golden/` 关键帧（清晰日/阴/雨/雪/雾/夜）哈希比对（容差 1e-3）。
- **性能预算**：1K 单帧 ≤ 3 s（2K ≤ 6 s）；建模缓存命中时 ≤ 0.5 s。
- **CI 全绿**：7 平台验收 + 自测 + 文档一致性 + 每日定时重建。

---

## 13. 迁移路线图

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 备份 + 本文件 + 建立 `tests/` 骨架 | 备份存在，agent.md 合入 |
| P1 | 新目录骨架与依赖（pyproject），旧代码物理搬移不删 | 旧功能可用，`--help` 走 typer |
| P2 | `scene3d`：房间 6 面 + 开口 + 材质 + **建模缓存(sha256)** | 二次运行命中缓存 |
| P3 | `light`：太阳**面光源**(角直径→半影) + 天空**穹顶积分** | 半影随距离单调；天空照度铺满房间 |
| P4 | `transport`：直接光 + 天空积分 + **互反射(辐射度)** | 房间整体提亮，能量守恒 |
| P5 | `surface`：BRDF + 湿面/雪 + **裂缝检测** + **镜面特殊处理** | 镜面反射可见、禁 6 镜面 |
| P6 | `pipeline`：批量/断点续跑/进度；CI 一键全天 | 480 帧可续跑 |
| P7 | `textoverlay` 移植 + 新增墨水浓度/颜料接口 | 与旧输出逐像素接近 |
| P8 | `interact`：CLI/TUI/向导（textual + pyfiglet） | 商业级手感 |
| P9 | 3DGS：从底图/照片重建房间（`gsplat`），缓存复用 | 不重复泼溅 |

---

## 14. 风险与回退

- 重构期间**旧实现保留可运行**（`--legacy` 开关），随时对比出图；
- 每阶段独立可回退（打快照 + tag）；
- 互反射矩阵规模受限于面片数，先 12×12/面，必要时降到 8×8；
- 3DGS 仅在有 GPU/足够时间时启用，CPU 走参数化房间 + 辐射度。

---

## 16. 渲染后端选型（不自己造渲染器）

**决策：物理正确性交给成熟光追器；我们只写"场景编译器"与"叠字"。**

| 后端 | 角色 | 平台 | 关键能力 |
|---|---|---|---|
| **Blender + Cycles（headless）** | **旗舰**（默认） | CI / 桌面 | 路径追踪、任意倾斜面、玻璃/水/色散、太阳**角直径→软阴影**、程序化材质、Text 对象、AgX/Filmic |
| **Mitsuba 3** | 备选 | CI | 可微、光谱、体积散射 |
| **POV-Ray** | 轻量备选 | CI / 桌面 | 经典 CPU 光追 |
| **自研 numpy 光追 + `embreex`** | **本机/离线兜底** | Android/Termux | 倾斜面、天空穹顶、水面单次反射；有 GPU/BVH 就用 embree |
| 光栅化类（pyrender/Three.js/VTK） | ❌ 不用 | — | 非物理 GI，水渍反射做不了 |

**分工（硬性）**
- 我们写：照片→**几何朝向/材质/水渍掩膜**的反推、**场景描述（SceneSpec）**、参数注册表→后端场景、调用与产物回收、叠字。
- 库负责：光线传输、BVH、采样、去噪、色彩管理、编解码。

**"任意墙面"模型**
- 墙面 = **任意平面四边形**（法线任意 → 自动支持倾斜墙/天花板/地板/斜面）
- 材质 = PBR（反照率/粗糙度/金属/折射率）+ **水膜层**（厚度/粗糙度/IOR=1.33）→ 水渍=水膜+粗糙度掩膜
- 来源三选一：① 照片反推 ② 贴图 ③ 程序化生成（水泥/石膏/砖）
- 叠字：几何投影到该平面（3D 文本或贴图），或渲染后后融合；两者都要支持

**SceneSpec（后端无关的中间层）**：见 `ownrender/render3d/scene.py`。
后端实现只读 SceneSpec，不许各写一套参数（参数一律来自注册表）。

### 16.1 高斯泼溅（3DGS）路线与**硬约束**

| 场景 | 方案 | 说明 |
|---|---|---|
| **单张底图（默认）** | **参数化房间 + 单图反推** | 单目深度/单应性 → 平面朝向、纹理、水渍掩膜；**不用 3DGS** |
| 多张照片（可选高级） | **3DGS 重建** | 需 ≥15~30 张有视差的照片；GPU 训练；离线跑，产物入缓存 |
| 纯程序化 | 材质库生成 | 无需照片 |

**⚠ 已知坑（写死在这里，防止以后踩）**
1. **单图做不了 3DGS**：3DGS 是"多视角重建"，单视图信息不足；市面"单图 3DGS"宣传不可信。
2. 3DGS 训练要 GPU；CPU 训练慢到不可用 → 只在 CI/有 GPU 时启用。
3. `gsplat`/`nerfstudio` 与 CUDA 版本强耦合；升级要整套一起升。
4. 3DGS 产物不适合直接做"叠字载体"：**要先把 splat 转成平面网格/贴图**（我们做这一步）。
5. Blender 4.x 改过 Principled BSDF 端口名（`Transmission` → `Transmission Weight`、
   `Specular` → `Specular IOR Level`）→ 生成器必须**双名兼容**（已实现）。

### 16.2 库使用的防坑清单（必须遵守）

- Blender：一律 `-b --factory-startup -noaudio`；脚本里所有搭建放进函数再调用；
  输出 16bit PNG；色彩管理显式指定（AgX/Filmic/Standard），不依赖默认。
- 渲染进程失败要**回传 stderr 尾部**（否则只看到"失败"两个字）。
- 任何后端都要能被**探测**：找不到就降级到自研 numpy 光追，**不许直接崩**。
- 3DGS/GPU 依赖全部列进 `pyproject[tool.optional-dependencies]`，主安装不引入。

---

## 17. 性能预算（硬指标）

| 指标 | 目标 | 量什么 |
|---|---|---|
| **冷启动 → 首图** | **≤ 90 s** | 进程启动 + 导入 + 缓存查找 + 建模（参数化）+ 渲染首帧 |
| **连续构建** | **≤ 10 s / 张** | 同房间命中缓存，只换时间/天气/文案 → 只重渲染 |
| 缓存命中路径 | ≤ 300 ms | 哈希 + 反序列化（我们的代码不许吃掉预算） |
| 场景构建（SceneSpec→脚本） | ≤ 300 ms | 同上 |
| 建模（缓存未命中，参数化） | ≤ 30 s | 单图反推 + 材质/水渍提取 |

**实现**：`ownrender/pipeline/perf.py`（计时器 + 预算守门），
`tests/test_perf.py` 在本地强制校验"我们的代码不吃预算"。
若某次渲染超时，先看"我们这段"的耗时，再看后端。

```bash
python -m ownrender --help                       # CLI（typer）
python -m ownrender tui                          # TUI（textual）
python tools/selftest.py                         # 全部守门测试
python tools/gen_cli_doc.py --check              # 文档与代码一致
python tools/batch_day.py --step 3 --weather clear   # 全天批量
python -m ownrender render --time ... --lat ... --lon ...
```
