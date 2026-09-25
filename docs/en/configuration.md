# Configuration

---

## 1. Three layers

```
① Factory defaults  (FACTORY_* inside config.py)
        ↓ overridden by
② User settings     (config/*.json, via settings centre or hand-edited)
        ↓ overridden by
③ CLI / wizard      (this run only, never written to disk)
```

**Precedence: ③ > ② > ①**

---

## 2. Files

| File | Contents | How to edit |
|---|---|---|
| `settings.json` | render defaults: resolution, aspect, SSAA, font, window, weather default, exposure/saturation, material coupling, log level, geolocation | settings centre / JSON |
| `lighting.json` | lighting & 3D scene coefficients: room size, camera, ACES gain, sky targets, vignette, material strength, ageing switches… | **settings centre (every field)** |
| `prompts.json` | AI prompts: wall description, scene profiles per light level, aspect descriptions, forbidden elements | settings centre / JSON |
| `token.json` | API token (AI mode). Auto `chmod 600` | settings centre → credentials |
| `device_location.json` | cached device location (optional) | `--set-location` or settings centre |

> `config/` is gitignored — never commit it.

---

## 3. Settings centre (TUI)

Main menu → `[3] 设置`:

```
  设置分组
   ▸ [0] 渲染与输出
     [1] 光照与 3D 场景        ← 60+ physical/visual coefficients
     [2] 天气默认
     [3] 文字与年代感
     [4] AI 提示词
     [5] 凭据（Token / NTP / 定位）
     [6] 日志
     [7] 恢复出厂
```

- **Lighting & 3D scene / AI prompts**: a generic editor lists **every field**
  (including nested groups) and adapts to bool / int / float / list / str.
  Nothing is hidden; changes save immediately.
- **Weather defaults**: preset + manual overrides (cloud/precip/visibility/
  humidity); leave `none` to fall back to the preset.
- **Credentials**: token (with connectivity test), NTP host, IP geolocation
  service, and **device location** (environment probe / re-acquire / manual
  entry / pick enabled providers / `su` escalation / clear cache).

---

## 4. CLI overrides

```bash
python main.py --offline-bg 微水泥 --ssaa 4 -y          # override render default
python main.py --offline-bg 微水泥 --weather rain -y     # override weather default
python main.py --offline-bg 微水泥 --weather cloudy --cloud 10 -y
```

Weather values have their own precedence chain:

```
--cloud flag  >  "cloud" in settings.json  >  the weather preset's cloud
```

---

## 5. Hand-editing JSON

### settings.json

```json
{
  "resolution": "2K", "aspect": "16:9", "ssaa": 8,
  "font": "", "font_ratio": 0.18, "font_anchor": "center",
  "font_pos_x": 50.0, "font_pos_y": 50.0,
  "background": "", "keep_lit": false,
  "window_orientation": "right", "window_scale": 0.65,
  "grid_rows": 3, "grid_cols": 2, "grid_frame_ratio": 0.18,
  "shadow_length": "auto", "weather_override": "auto",
  "smart_wrap": true,
  "visual_exposure": 1.0, "visual_saturation": 1.0,
  "material_coupling": 0.0,
  "location_providers": [], "location_use_su": false,
  "log_level": "INFO", "log_to_file": false,
  "ntp_host": "", "geo_service": ""
}
```

| Key | Meaning |
|---|---|
| `background` | default texture name (no extension); empty = first found / ask in wizard |
| `weather_override` | default preset: `auto`/`clear`/`cloudy`/`overcast`/`rain`/`snow`/`haze` |
| `cloud` `precip` `visibility` `humidity` | manual weather overrides; `null` = use preset |
| `visual_exposure` / `visual_saturation` | image tweak defaults |
| `material_coupling` | glyph opacity modulated by wall material (0 = off) |
| `location_providers` | enabled geolocation sources, e.g. `["termux","timezone"]`; **empty = all, in priority order** |
| `location_use_su` | Android: allow `su -c` for `dumpsys location` |
| `smart_wrap` | punctuation-aware line breaking |

### lighting.json (excerpt)

```json
{
  "scene": {
    "room_w_m": 4.0, "room_h_m": 3.0, "room_d_m": 4.0,
    "window_side": "right", "window_w_m": 1.2, "window_h_m": 1.5,
    "window_cy_m": 1.5, "window_cz_m": 1.5,
    "grid_rows": 3, "grid_cols": 2, "grid_frame_ratio": 0.10,
    "camera_pos_m": [0.0, 1.5, 3.0], "camera_fov_deg": 60
  },
  "aces_gain": 1.25,
  "ambient_target_sun_max": 0.45, "ambient_target_sun_min": 0.28,
  "ambient_target_twilight": 0.20, "ambient_target_moon": 0.17,
  "ambient_target_none": 0.15,
  "vignette_strength": 0.15, "material_strength": 0.8,
  "aged_enabled": true, "shadow_blue_tint": 0.05
}
```

These are **physics/visual coefficients** and directly change the output.
Edit them through the settings centre; `设置 → 恢复出厂` rolls back.

---

## 6. Token precedence

`--token` > `AGNES_API_TOKEN` > `config/token.json`

```bash
python main.py --ai -t "title" --token sk-xxxx -y
export AGNES_API_TOKEN="sk-xxxx"
```

---

## 7. Backup / reset

```bash
cp -r config config.bak
python main.py --reset-config      # or: 设置 → 恢复出厂
rm -rf config/
```

On startup the program **self-heals** missing config keys (adds them, never
overwrites existing values).

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / macOS / Android `.so`, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
