# OwnRender

**A physically-based wall + window-light renderer.** Feed it a flat, evenly-lit
material texture and a line of text; get back a wall lit by a real sunbeam that
changes with time, weather and window orientation — with weathered vermilion
lettering burned into the surface.

> 中文: [README.md](README.md) · Docs index: [docs/en/](docs/en/index.md)

---

## What it does

Lighting here is **not a filter**:

- Sun and moon positions are computed from latitude, longitude and UTC time.
- Atmospheric transmittance is computed **per wavelength** from Rayleigh/Mie
  scattering: `T(λ)=exp(-(τ_R(λ)+τ_M)·AM)` — low sun automatically turns orange.
- The indoor wall is produced by **ray tracing** a 3D room with a window.
- Output goes through ACES tone mapping, camera effects (vignette, CMOS curve)
  and is encoded to sRGB.
- Diffuse **sky light** is modelled so a wall stays correctly lit even when no
  direct beam enters (it will not go pitch black in daytime).

```
flat texture ─► Retinex ─► PBR material ─► 3D scene + ray tracing
             ─► ACES ─► camera effects ─► exposure/saturation ─► sRGB
             ─► text SSAA ─► ageing ─► contact shadow ─► optical composite
```

---

## Features

- **Real astronomy** — sun/moon azimuth & altitude, sunrise/sunset, twilight,
  moon phase and moonlight brightness
- **Per-wavelength atmosphere** — physically motivated colour shift
- **Sky diffuse term** — ambient illumination follows sun altitude and cloud
- **Window light patch** — position, stretch and shear driven by sun angles,
  with soft penumbra
- **Window geometry** — orientation (E/W), size, grid rows/cols, frame ratio,
  shadow multiplier
- **Weather system** — 7 presets plus fully manual cloud/precip/visibility/
  humidity, with a live effect preview
- **Cross-platform geolocation** — Termux / Android / Linux (GeoClue, gpsd,
  ModemManager) / macOS / Windows / timezone fallback / IP lookup / local cache
- **Text rendering** — SSAA, punctuation-aware line breaking, physical
  vermilion pigment compositing, contact shadow, multi-octave ageing noise,
  optional material coupling
- **Mostly offline** — only the optional AI generation mode needs the network

---

## Requirements

| Item | Requirement |
|---|---|
| Python | 3.9+ (developed on 3.12) |
| Libraries | **numpy**, **Pillow**, **requests** |
| Optional | `uv` |
| Platforms | Linux / macOS / Windows / Termux / Android (proot) |

```bash
pip install numpy Pillow requests
```

---

## Quick start

```bash
python main.py
```

You get a TUI. Pick a mode, then the **parameter wizard** lists every step at
once and lets you jump back and edit any of them before rendering:

```
   [0] text      谎如昨日， / 嗤笑今朝
   [1] font      AaXiuKai-2.ttf
   [2] layout    ratio0.18 center (50,50) SSAA8
   [3] texture   微水泥.png
   [4] time      now 06-21 12:00 (UTC+8)
   [5] location  Beijing (39.90,116.41)
   [6] weather   clear
   [7] light     right grid3x2 shadow auto
   [8] render    SSAA8 seed=None
   [9] ageing    coupling0 diffusion0.2 shadow0.25
   [10] image    exposure1 saturation1
   [11] output   ./output
 ▸ [12] ✓ render        [13] abort
```

---

## Modes

| Mode | Input | Lighting | Network |
|---|---|---|---|
| **AI generate** `--ai` | prompt + token | AI paints the lit wall directly (no ray tracing) | required |
| **Offline lighting** `--offline-bg NAME` | a texture in `background/` | **ray-traced physical lighting** | not required |
| **Custom** `-i PATH` | any image | no lighting, text only | not required |

---

## Command line

```bash
# Minimal offline render + text
python main.py --offline-bg 微水泥 -y

# Explicit time / place / weather (--time accepts an explicit UTC offset)
python main.py --offline-bg 微水泥 \
    --time "2025-06-21T12:00:00+08:00" \
    --lat 39.9042 --lon 116.4074 --weather clear -y

# Manual weather: cloudy, 30% cloud, 10 km visibility, 55% humidity
python main.py --offline-bg 青砖墙 --weather cloudy \
    --cloud 30 --visibility 10000 --humidity 55 -y

# Text only on your own image
python main.py -i ./my_wall.png -t "谎如昨日，嗤笑今朝" -y

# Image tweaks + heavier ageing
python main.py --offline-bg 锈蚀钢板 --exposure 1.15 --saturation 0.9 \
    --material-coupling 0.4 --diffusion 0.25 -y

# Queries
python main.py --list-backgrounds
python main.py --list-fonts
python main.py --show-config
python main.py --help
```

Full reference: **[docs/en/cli.md](docs/en/cli.md)**.

---

## Assets

- `background/` — **16 flat, evenly-lit material textures** (micro-cement,
  coarse plaster, red brick, fair-faced concrete, marble, tile, wood veneer,
  rusted steel, grey brick…). Prompts in [background/README.md](background/README.md).
- `fonts/` — 3 Chinese fonts, **collected from the public internet and included
  for non-commercial study only**. See [CREDITS.md](CREDITS.md).

Drop your own files into those folders and they are picked up automatically.

---

## Expected results

The repo ships **no rendered output** — render your own to verify:

| Scenario | Settings | What you should see |
|---|---|---|
| Clear noon | `--time …12:00 --weather clear`, east window | weak direct beam (sun near the window plane); wall lit **uniformly by sky light**, cool white |
| Clear morning | `--time …09:00 --weather clear` | a **crisp grid-shaped light patch**, sharp edges, offset to one side |
| Dusk | `--time …18:30`, west window | patch **stretched and orange-red**, long low shadows |
| Deep night | `--time …23:00` | very dark blue; with moonlight a faint cool-blue patch |
| Overcast / haze | `--weather overcast/haze` | patch edge **much softer** or gone, low contrast overall |
| Rain | `--weather rain` | blurred patch + **water streaks** on the wall |
| Snow | `--weather snow` | **snow highlights**, cooler colour temperature |
| Text (default) | vermilion pigment | matte vermilion lettering sunk into the texture, slight oxidation grain |
| Text (heavy ageing) | `--noise-low 0.3 --diffusion 0.4 --oxidation 0.5` | mottled, frayed edges — like an old slogan |
| Text (clean) | `--noise-low 0.05 --diffusion 0.1 --oxidation 0` | clean and sharp, close to modern print |

More: [docs/en/effects.md](docs/en/effects.md).

---

## Layout

```
OwnRender/
├── main.py              entry point
├── config.py            constants, config IO, font & line-breaking helpers
├── frame_light/         lighting: astro, light, geometry, scene3d, raytrace, scene
├── frame_render/        rendering: pipeline, retinex, material, text, compose
├── frame_interact/      TUI: tui, wizard, settings, runner, cli, offline, ai
├── background/          material textures
├── fonts/               fonts
├── tools/               helper scripts
└── docs/                documentation (Chinese / English)
```

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)** — full text in [LICENSE](LICENSE)

```
Copyright (C) 2025 yingo-server and OwnRender contributors
```

- ✅ Free to use, modify and distribute, **including commercially**
- 🔁 **Derivatives must be open source**: when you distribute the program, or
  **offer it to users over a network**, you must provide the complete
  corresponding source under AGPL-3.0 (see AGPL §13)
- 🧾 **No warranty**: provided "AS IS", without any warranty or liability
  (AGPL §15–§17)
- 💼 If you **cannot accept AGPL's source-disclosure obligations** (e.g. closed
  products, closed SaaS), contact the author for a **commercial license**
  (dual licensing)
- ⚠️ Third-party assets in `fonts/` and `background/` are **outside the scope of
  the code license** and keep their own terms — see [CREDITS.md](CREDITS.md)

Asset takedown requests ([DMCA]) or commercial licensing: open an **Issue**.

> 📌 The program and CLI still use the historical name `agnes-render` (banner,
> `--help` prog name); it is the same project as the OwnRender repository.

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / Android `.so`; x86 / x86_64 / arm64 / armv7, built by CI with Nuitka) — **download & usage → [docs/en/binaries.md](docs/en/binaries.md)**
