# Architecture

---

## 1. Three isolated sub-frameworks

```
frame_interact/   interaction: TUI, wizard, settings, CLI, mode orchestration
      │ calls
      ├──────────────► frame_light/    lighting: astro → light → geometry → ray tracing
      └──────────────► frame_render/   rendering: Retinex → material → pipeline → text
```

Dependencies are **one-way** (`interact → light/render`); `light` and `render`
do not import each other (the pipeline lazily imports scene data) to avoid
circular imports. `config` is the only shared module.

---

## 2. Modules

### frame_light — lighting

| File | Responsibility |
|---|---|
| `astro.py` | sun/moon position, atmospheric scattering, weather fetch, **cross-platform geolocation providers**, timezone |
| `light.py` | `compute_light()`: (time + place + weather + window) → physical light quantities |
| `geometry.py` | patch centre/size/shear/penumbra/shadow offset, times the **incidence factor** |
| `scene3d.py` | 3D room + camera, `win_bbox` (window projected on the wall) |
| `raytrace.py` | direct light + shadow + penumbra + ambient (sky light) |
| `scene.py` | scene light composition |
| `utils.py` | angle / azimuth wording helpers |

### frame_render — rendering

| File | Responsibility |
|---|---|
| `pipeline.py` | **top-level orchestration**: Retinex → material → trace → ACES → camera → exposure/saturation → encode |
| `retinex.py` | illuminant/reflectance decomposition |
| `material.py` | PBR channel extraction (albedo/roughness/height/water…) |
| `text.py` | text SSAA, ageing, contact shadow, optical composite |
| `compose.py` | sRGB encode/decode |
| `patch.py` | patch helpers (legacy, not on the main path) |
| `utils.py` | colour spaces, ACES, noise, array shifting |

### frame_interact — interaction

| File | Responsibility |
|---|---|
| `tui.py` | TUI toolkit: colour (CJK-aware width), panels, menus, inputs, `Wizard`, `edit_mapping` |
| `wizard.py` | parameter wizard: the full `Plan` + per-step editors |
| `settings.py` | settings centre (8 groups) + info/self-check |
| `runner.py` | main menu, mode dispatch |
| `cli.py` | argparse table, mode detection |
| `offline.py` | offline-lighting and custom-image orchestration |
| `ai.py` | online AI generation orchestration |
| `progress.py` | progress reporting |

---

## 3. Data flow (offline lighting)

```
flat texture + text
        │
  retinex.split()      → albedo + original illuminant S
        │
  material.extract()   → roughness / height / water …
        │
  light.compute_light(lat, lon, time, weather, window_orientation)
        → source / az / alt / irradiance / colour
        → ambient (sky light)
        → patch geometry + shadow offset
        │
  raytrace.trace()     → I_traced (linear)
        │
  ACES + camera effects (vignette / CMOS / tint) + exposure / saturation
        │
     lit.png ──► text.fuse()  (SSAA → ageing → contact shadow → multiplicative composite)
        │
    final.png
```

Lighting and text are **strictly separated**: lighting only produces `lit.png`,
text only consumes it — so editing the text never re-runs the ray tracer.

---

## 4. Key algorithms

### 4.1 Sun position

Standard low-precision solar algorithm (day-of-year → declination + equation of
time → hour angle → azimuth/altitude). Verified: Beijing 2025-06-21 noon gives
altitude `73.53°` vs. the analytic `90° − |39.9° − 23.44°| = 73.54°`
(error 0.01°).

### 4.2 Air mass & per-wavelength transmittance

```
AM = 1 / (sin(alt) + 0.50572 · (alt + 6.07995)^(-1.6364))     # Kasten-Young

τ_R(λ) = 0.098 · (λ/550)^(-4.08)      # stronger scattering in the blue
τ_M    = 0.05 + cloud term + visibility term
T(λ)   = exp( -(τ_R(λ) + τ_M) · AM )
```

Low sun → relatively higher red transmission → automatic orange/red shift.

### 4.3 Sky (diffuse) term

```
sky(sun_alt, cloud) = 0.22 · sin(alt)^0.6 · (1 − 0.70·(cloud/100)^1.8)
```

Zero below the horizon (twilight is handled separately). This is what keeps a
daytime wall from going pitch black when no direct beam enters.

### 4.4 Window incidence factor

```
inc_factor = max(0.02, sqrt( max(0, cos(alt)·cos(az_rel)) ))
irradiance *= inc_factor
```

`az_rel = sun azimuth − window normal azimuth`. Grazing incidence → ~0, which
is why an east window gets almost no direct light at noon.

### 4.5 Patch geometry

```
cx = 0.5 − sin(az_rel)·0.35
cy = 0.55 − min(1, alt/60)·0.25
stretch = window_aspect / tan(alt)
```

### 4.6 Tone mapping & tweaks

```
I_out = ACES(I_traced · gain)
I_out = camera_effects(I_out)
I_out = lum + (I_out − lum)·saturation
I_out = I_out · exposure
```

### 4.7 Text ageing

```
α = α₀ · (1 − low·(1−n_low)) · (1 − mid·(1−n_mid))
edge = α − erode(α)
α = α + edge · (n_high−0.5)·2·high
α = α + max(0, blur(α)−α) · diffusion
α[oxidation dots] *= (1 − oxidation·0.5)
```

### 4.8 Composite

```
L_out = L_wall·(1 − occ·s) · [(1−α) + α·ρ_cinnabar]
```

---

## 5. Configuration

```
config.py
 ├─ FACTORY_SETTINGS   → config/settings.json
 ├─ FACTORY_LIGHTING   → config/lighting.json
 ├─ FACTORY_PROMPTS    → config/prompts.json
 └─ module constants (colour spaces, ageing defaults, font/line-break helpers)
```

Runtime overrides: `config.TEXT_MATERIAL_COUPLING`,
`config.VISUAL_EXPOSURE`, `config.VISUAL_SATURATION`.

---

## 6. Extension points

| Goal | Where |
|---|---|
| Add a texture | drop an image into `background/` (**no code change**) |
| Add a font | drop a font into `fonts/` (**no code change**) |
| Add a city preset | `CITY_PRESETS` in `wizard.py` |
| Add a weather preset | `config.WEATHER_PRESETS` + `wizard.WEATHER_UI` |
| Add a geolocation source | write `_p_xxx()` in `astro.py`, register in `LOCATION_PROVIDERS` |
| Add N/S window orientations | `config.WINDOW_SIDE_AZ` + `scene3d` |
| Change render defaults | `config.FACTORY_SETTINGS` or the settings centre |
| Change lighting physics | settings centre → lighting & 3D scene (60+ fields) |
| Change AI prompts | settings centre → AI prompts |
| Add a CLI flag | `cli.build_parser()` + wire it in `wizard.plan_from_args` |

---

## 7. Known legacy / limitations

- `frame_render/patch.py::render_light_patch()` and `compose.synthesize()` are
  **not called** on the main path (remnants of an earlier multi-layer patch
  approach), kept for reference.
- Window orientation supports only `left`/`right` (west/east); no north/south yet.
- AI mode paints an already-lit wall and does **not** run the ray tracer, so it
  is physically less consistent than offline mode.