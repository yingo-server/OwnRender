# Command-line reference

`python main.py [options…]`

> No options → TUI main menu.
> Options **without `-y`** → they pre-fill the wizard (you can still tweak).
> Options **with `-y`** → fully non-interactive render.

---

## 1. Mode

| Flag | Meaning |
|---|---|
| `--ai` | AI generation mode (needs token + network) |
| `--offline-bg NAME` | **Offline lighting mode**: ray-traced lighting on a texture from `background/` |
| `-i PATH` / `--input-image PATH` | Custom image, **no lighting**, text only |
| `--background NAME` | Pick texture by name (does not by itself select offline mode) |
| `--keep-lit` | Keep the intermediate `*_lit.png` |

Detection priority: `-i` > `--offline-bg` > `--ai` > other generation flags → AI > menu.

---

## 2. Input / output

| Flag | Default | Notes |
|---|---|---|
| `-t TEXT` / `--text TEXT` | `谎如昨日，嗤笑今朝` | text to burn in; `\n` forces a line break |
| `-o OUT` / `--output OUT` | `./output` | output directory (created if missing) |
| `--output-name NAME` | `LIT` / `AI` | filename prefix |

Result: `{prefix}_{YYYYMMDD}_{HHMMSS}_final.png`

---

## 3. Text & layout

| Flag | Range | Default | Notes |
|---|---|---|---|
| `-f FONT` | filename in `fonts/` | auto | with or without extension |
| `--font-ratio F` | 0.02 – 0.60 | `0.18` | glyph height as a fraction of image height |
| `--font-anchor A` | `center` `tl` `tr` `bl` `br` `tc` `bc` `lc` `rc` | `center` | |
| `--font-pos-x P` | 0 – 100 | `50` | anchor x in % |
| `--font-pos-y P` | 0 – 100 | `50` | anchor y in % |
| `--ssaa N` | 1 – 16 | `8` | supersampling factor |

---

## 4. Window & lighting

| Flag | Range | Default | Notes |
|---|---|---|---|
| `--window-orientation` | `left` `right` | `right` | `right` = east (morning sun), `left` = west (afternoon sun) |
| `--window-scale F` | 0.2 – 1.2 | `0.65` | window size relative to the room |
| `--grid-rows N` | 1 – 8 | `3` | |
| `--grid-cols N` | 1 – 8 | `2` | |
| `--grid-frame F` | 0.02 – 0.5 | `0.18` | frame/mullion thickness |
| `--shadow-length V` | `auto` or 0.5 – 4.0 | `auto` | shadow / patch offset multiplier |

Orientation determines *when* a direct patch can appear — see
[effects.md](effects.md) §2.

---

## 5. Time & location

| Flag | Notes |
|---|---|
| `--time S` | **Prefer an explicit offset**: `2025-06-21T12:00:00+08:00`. A bare `YYYY-MM-DD HH:MM` is interpreted in the machine's timezone |
| `--no-ntp` | use the system clock |
| `--ntp-host HOST` | pin a specific NTP server |
| `--lat F` / `--lon F` | explicit coordinates (most reliable) |
| `--city NAME` | display/record only |
| `--gps` | force device location (cross-platform provider chain) |
| `--ip-loc` | force IP geolocation |
| `--no-gps` | disable automatic geolocation |
| `--geo-service NAME` | pin one IP geolocation service |
| `--set-location LAT,LON[,CITY]` | write the local cache and **exit** |

Provider chain (first success wins):

```
termux-location → Android(dumpsys/cmd) → Linux GeoClue
→ Linux gpsd → Linux ModemManager → macOS CoreLocation
→ Windows Geolocator → timezone fallback → local cache
```

> Lighting is computed in **UTC**. If your machine is on UTC but you want
> "Beijing noon", pass `+08:00` explicitly.

---

## 6. Weather

| Flag | Range | Notes |
|---|---|---|
| `--weather` | `auto` `clear` `cloudy` `overcast` `rain` `snow` `haze` | preset |
| `--cloud F` | 0 – 100 | cloud cover % |
| `--precip F` | 0 – 50 | precipitation mm |
| `--visibility F` | 200 – 50000 | visibility m |
| `--humidity F` | 0 – 100 | humidity % |

Precedence: **flag > settings default > preset**.

| Preset | Cloud | Effect |
|---|---|---|
| `clear` | 0% | strongest direct light, sharpest patch |
| `cloudy` | 45% | softer patch |
| `overcast` | 90% | almost no direct light, low contrast |
| `rain` | 95% | water streaks, very soft patch |
| `snow` | 90% | snow highlights, cooler |
| `haze` | — | low visibility, smeared patch |
| `auto` | — | live weather lookup (falls back to clear offline) |

---

## 7. Output size (AI mode only)

| Flag | Values | Default |
|---|---|---|
| `-r` / `--resolution` | `1K` `2K` `3K` `4K` | `2K` |
| `-a` / `--aspect` | `1:1` `3:4` `4:3` `16:9` `9:16` `2:3` `3:2` `21:9` | `16:9` |

> ⚠️ **4K is rate limited (RPM = 1)** — use 1K/2K for batches.
> These flags do nothing in offline mode (output size = texture size).

---

## 8. Render

| Flag | Range | Default | Notes |
|---|---|---|---|
| `--ssaa N` | 1 – 16 | `8` | supersampling |
| `--seed N` | int | random | fixes the noise pattern for reproducibility |
| `--light-level N` | 0 – 12 | auto | override automatic light level classification |
| `--wall-desc TEXT` | string | — | wall description (AI prompt) |
| `--keep-lit` | flag | off | keep the intermediate lit image |

---

## 9. Image tweaks

| Flag | Range | Default |
|---|---|---|
| `--exposure F` | 0.2 – 3.0 | `1.0` |
| `--saturation F` | 0.0 – 3.0 | `1.0` |

Applied after ACES, before sRGB encoding.

---

## 10. Pigment / ageing

| Flag | Range | Default |
|---|---|---|
| `--cinnabar R G B` | 0 – 1 | `0.52 0.055 0.048` |
| `--noise-low F` | 0 – 0.6 | `0.12` |
| `--noise-mid F` | 0 – 0.6 | `0.10` |
| `--noise-high F` | 0 – 0.6 | `0.06` |
| `--diffusion F` | 0 – 0.8 | `0.20` |
| `--oxidation F` | 0 – 0.8 | `0.30` |
| `--shadow-strength F` | 0 – 1.0 | `0.25` |
| `--material-coupling F` | 0 – 1.0 | `0.0` |

Compositing: `L_out = L_wall·(1 − occ·s)·[(1−α) + α·ρ]`

---

## 11. Control

| Flag | Notes |
|---|---|
| `--token T` | API token (highest precedence) |
| `--settings` | open the settings centre and exit |
| `--no-color` | disable ANSI colour (also honours `NO_COLOR`) |
| `-y` / `--yes` | non-interactive |
| `-v` / `--verbose` | DEBUG logging |
| `--log-level L` | `DEBUG` `INFO` `WARN` `ERROR` |
| `--log-file` | also write `config/logs/agnes-render.log` |
| `--dry-run` / `--no-render` | predict only, do not render |

---

## 12. Queries

`--list-fonts`, `--list-backgrounds`, `--list-sizes`, `--list-ntp`,
`--list-services`, `--show-config`, `--reset-config`, `--version`

Query flags never enter the menu; they print and exit.

---

## 13. Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | error (missing texture, location failure, …) |
| `130` | interrupted (Ctrl-C) |

---

## 14. Examples

```bash
# minimal offline
python main.py --offline-bg 微水泥 -y

# clear morning, east window, Beijing
python main.py --offline-bg 青砖墙 \
    --time "2025-06-21T09:00:00+08:00" --lat 39.9042 --lon 116.4074 \
    --weather clear --window-orientation right -y

# dusk, west window
python main.py --offline-bg 暖色夯土 \
    --time "2025-06-21T18:30:00+08:00" --lat 39.9042 --lon 116.4074 \
    --weather clear --window-orientation left -y

# overcast, low contrast
python main.py --offline-bg 粗灰泥 --weather overcast -y

# rainy night
python main.py --offline-bg 锈蚀钢板 \
    --time "2025-11-11T22:00:00+08:00" --lat 31.23 --lon 121.47 \
    --weather rain -y

# clean bold lettering
python main.py --offline-bg 大理石 -t "静水流深" \
    --font-ratio 0.30 --noise-low 0.05 --diffusion 0.10 --oxidation 0 -y

# weathered slogan
python main.py --offline-bg 旧石灰 -t "为人民服务" \
    --font-ratio 0.22 --noise-low 0.30 --diffusion 0.40 --oxidation 0.50 -y

# text only on your own image
python main.py -i ~/Pictures/wall.jpg -t "谎如昨日，嗤笑今朝" -y

# image tweaks
python main.py --offline-bg 白色乳胶漆 --exposure 1.15 --saturation 0.9 -y

# device location + live weather
python main.py --offline-bg 微水泥 --gps --weather auto -y
```

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / macOS / Android `.so`, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
