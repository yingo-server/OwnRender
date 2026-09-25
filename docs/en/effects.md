# Effects — what to expect

The repository ships **no rendered output**. This page describes what each
setting produces so you can verify your own renders.

---

## 1. The mental model

> Lighting is driven by the **sun/moon position**, which is driven by
> **time + latitude/longitude + window orientation**.

So before touching any coefficient, answer:

1. What time is it (local)?
2. Where are you (lat/lon)?
3. Which way does the window face (east/west)?
4. Is there cloud cover?

Those four determine the whole mood.

---

## 2. Time × orientation — when a light patch appears

`--window-orientation right` = east-facing, `left` = west-facing.

| Local time | Sun | East window (`right`) | West window (`left`) |
|---|---|---|---|
| 05:00–07:00 | low, warm | **direct**, patch stretched & orange | none |
| 07:00–10:00 | mid-high | **direct**, crisp patch | none |
| 10:00–14:00 | high | almost none (sun near the window plane); wall lit by **sky light** | same |
| 14:00–17:00 | mid-high | none | **direct** |
| 17:00–19:00 | low, warm | none | **direct**, stretched & orange-red |
| 19:00–05:00 | below horizon | none; with moonlight a faint cool-blue patch | same |

> This is **physically correct**, not a bug. "Why is there no patch at noon?" —
> because an east window genuinely receives no direct sun at noon.

---

## 3. Scenario cheat-sheet

| # | Want | Settings | Expected |
|---|---|---|---|
| ① | dawn warmth | `right` + `06:30` + `clear` | long orange-gold band across the wall |
| ② | bright morning | `right` + `09:00` + `clear` | crisp grid patch, sharp edges |
| ③ | flat noon | any + `12:00` + `clear` | no patch; wall **uniformly sky-lit**, cool white |
| ④ | afternoon sun | `left` + `15:30` + `clear` | patch off to one side, warming up |
| ⑤ | dusk | `left` + `18:30` + `clear` | patch strongly stretched, orange-red, long shadows |
| ⑥ | overcast | any + `overcast` | patch almost gone, low contrast, grey |
| ⑦ | haze | any + `haze` | patch edges smeared, hazy look |
| ⑧ | rain | any + `rain` | very blurry patch + **water streaks** |
| ⑨ | snow | any + `snow` | **snow highlights**, cooler |
| ⑩ | deep night | any + `23:00` | very dark, blue; ambient only |
| ⑪ | moonlit | any + `02:00` near full moon | faint cool-blue patch (moon albedo is low) |

---

## 4. Text overlay

Compositing is **multiplicative reflection**, not a sticker:

```
L_out = L_wall · (1 − occ·s) · [(1−α) + α·ρ]
                ↑ contact shadow     ↑ vermilion reflectance
```

`α` = glyph opacity, `ρ` = vermilion reflectance (`--cinnabar`, default
`0.52 0.055 0.048`). **Consequence**: the text darkens in shadow just like
real paint.

| Style | Flags | Look |
|---|---|---|
| **Clean / modern** | `--noise-low 0.05 --noise-mid 0.04 --noise-high 0.02 --diffusion 0.10 --oxidation 0` | sharp edges, print-like |
| **Default** | none | slight mottling, faint oxidation grain |
| **Weathered slogan** | `--noise-low 0.30 --noise-mid 0.20 --noise-high 0.12 --diffusion 0.40 --oxidation 0.5` | heavily mottled, frayed edges |
| **Sunk into the wall** | `--material-coupling 0.5` | opacity follows wall relief — great on brick/stone |

Font size: `--font-ratio` 0.08–0.12 long lines · 0.15–0.22 (default) ·
0.28–0.40 short punchy phrases.

---

## 5. Image tweaks

| Want | Flag |
|---|---|
| brighter / airier | `--exposure 1.1 ~ 1.3` |
| darker / moodier | `--exposure 0.8 ~ 0.95` |
| desaturated, restrained | `--saturation 0.6 ~ 0.8` |
| richer material colour | `--saturation 1.1 ~ 1.3` |

Applied *after* ACES tone mapping, so highlights never clip when you brighten.

---

## 6. Picking a texture

| Mood | Textures |
|---|---|
| modern minimal | 微水泥 (micro-cement), 白色乳胶漆 (white emulsion), 莫兰迪涂料 |
| industrial | 清水混凝土, 水泥砌块, 锈蚀钢板 |
| traditional / aged | 青砖墙, 旧石灰, 草泥墙, 暖色夯土 |
| refined | 大理石, 木饰面, 瓷砖 |
| heavy / urban | 红砖墙, 石砌墙 |

Fine textures give cleaner patches; brick/stone benefit from
`--material-coupling`.

---

## 7. Verify numerically

### ① Is the texture flat?

```python
from PIL import Image
import numpy as np
a = np.asarray(Image.open("background/微水泥.png").convert("RGB"), dtype=np.float32)
h, w, _ = a.shape
cy, cx = h // 4, w // 4
ctr = a[cy:cy*3, cx:cx*3].mean()
crn = np.concatenate([a[:cy, :cx].reshape(-1,3), a[:cy, -cx:].reshape(-1,3),
                      a[-cy:, :cx].reshape(-1,3), a[-cy:, -cx:].reshape(-1,3)]).mean()
print("center", round(ctr,1), "corners", round(crn,1), "delta", round(ctr-crn,1))
```

Delta should be small (< 15/255). Large delta = the texture has baked-in
lighting and will be flattened by the re-lighting pass.

### ② Does the output match the intended time?

| Time | Reasonable mean brightness |
|---|---|
| clear noon | 140 – 190 |
| clear morning/afternoon | 120 – 180 |
| dusk | 80 – 150 |
| deep night | 20 – 50 |

A "daytime" image stuck around 30 means something is off (commonly: the time
was interpreted as UTC).

### ③ Is there a patch?

A patch is a region clearly brighter than its surroundings. If it's daytime,
`clear`, and you see none, check whether the sun is *behind* the window
(see section 2).

---

## 8. Reproducibility

```bash
python main.py --offline-bg 微水泥 --seed 12345 -y
```

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / macOS / Android `.so`, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
