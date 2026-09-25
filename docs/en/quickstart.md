# Quickstart

Your first render in 5 minutes.

---

## 0. Prerequisites

```bash
pip install numpy Pillow requests
```

Only **offline lighting + text** is guaranteed to work without `requests`.

---

## 1. Run it

```bash
cd OwnRender
python main.py
```

Main menu:

```
  主菜单
     [0] AI 生成底图 + 叠字          （在线，需要 Token）
   ▸ [1] 内置底图 + 物理光照 + 叠字   （离线）
     [2] 自定义图片 + 叠字            （离线，不光照）
     [3] 设置
     [4] 信息 / 环境自检
     [5] 退出
     回车=1     a/b/c/s/i/q 快捷选择
```

Pick **`[1]` (offline)** first — it needs no token and no network.

---

## 2. The parameter wizard

Every step is listed at once; you can jump back and edit any of them.

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
────────────────────────────────────────────────────────────────────────────
  选择要修改的步骤（回车=确认）
   ▸ [12] ✓ 开始生成
     [13] 放弃
```

- Type a **number** to edit that step; you are returned to the overview
- **Enter** = render with the current settings
- `[13]` = abort

The TUI is in Chinese (`文字` = text, `字体` = font, `排版` = layout,
`底图` = texture, `时间` = time, `位置` = location, `天气` = weather,
`光照` = lighting, `渲染` = render, `年代感` = ageing, `画面` = image
tweaks, `输出` = output). Editing prompts accept plain numbers/`y`/`n`.

---

## 3. Weather in detail

```
  天气
   ▸ [0] 自动（auto）      按季节/气候推算云量
     [1] 晴（clear）       云 0%，直射最强、光斑边界最锐
     [2] 多云（cloudy）    云 45%，光斑变软
     [3] 阴（overcast）    云 90%，几乎无直射、散射为主
     [4] 雨（rain）        云 95%，叠加水痕
     [5] 雪（snow）        云 90%，叠加雪花亮点
     [6] 雾霾（haze）      能见度低，光斑明显模糊
     [7] 手动微调（云量/降水/能见度/湿度）   完全放开
```

Option `[7]` lets you override each of cloud / precip / visibility / humidity
(Enter = keep, `none` = fall back to the preset), then shows a live prediction:

```
┌─ 效果预测 ──────────────────────────────────────────────┐
│ 云量/降水  30%  0.0mm  能见 10.0km  湿度 55%
│ 主光源     sun   高度 +37.3°   方位 +89.2°
│ 辐照度     0.5xx   天光 0.2xx
│ 可达性     阳光可达
└─────────────────────────────────────────────────────────┘
```

The **可达性 (reachability)** line tells you whether a direct sun patch will
appear at all — very useful when nothing shows up.

---

## 4. Output

```
output/
├── LIT_20250621_060000_lit.png     (only if "keep lit" is on)
└── LIT_20250621_060000_final.png   (the final image)
```

---

## 5. Same thing from the command line

```bash
# Defaults: current time/place, first texture
python main.py --offline-bg 微水泥 -y

# Explicit: 2025-06-21 12:00 (+08:00), Beijing, clear
python main.py --offline-bg 微水泥 \
    --time "2025-06-21T12:00:00+08:00" \
    --lat 39.9042 --lon 116.4074 \
    --weather clear -y
```

- `-y` / `--yes` → fully non-interactive
- Without `-y`, CLI values merely **pre-fill** the wizard (so you can still
  tweak before rendering)

---

## 6. Next

- Tune the look → [effects.md](effects.md)
- Every flag → [cli.md](cli.md)
- Swap fonts/textures → [../../fonts/README.md](../../fonts/README.md),
  [../../background/README.md](../../background/README.md)