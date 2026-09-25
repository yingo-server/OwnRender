# Dependencies & Installation

---

## 1. Only three libraries

| Library | Version | Used for | Required |
|---|---|---|---|
| **numpy** | ≥ 1.20 | all numerics (lighting, ray tracing, image ops) | **yes** |
| **Pillow** | ≥ 8.0 | image IO, font rasterisation, filters, resampling | **yes** |
| **requests** | ≥ 2.20 | AI generation, NTP, IP geolocation, weather | optional* |

\* `requests` is not needed at all for **offline lighting** or **text-only**
modes. Nothing crashes if it is missing — those features simply degrade.

Tested on: Python 3.12.3 / numpy 2.5.3 / Pillow 12.3.0 / requests 2.34.2

---

## 2. Install

```bash
# pip
python -m pip install numpy Pillow requests

# uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv && uv pip install numpy Pillow requests
.venv/bin/python main.py

# distro packages
sudo apt install python3-numpy python3-pil python3-requests   # Debian/Ubuntu
brew install python numpy pillow && pip3 install requests      # macOS
pkg install python-numpy python-pillow && pip install requests # Termux
```

---

## 3. First run

```bash
python main.py
```

`config/` is created automatically:

```
config/
├── settings.json    render defaults
├── lighting.json    lighting & 3D scene coefficients
├── prompts.json     AI prompts (online mode)
└── token.json       API token (600), AI mode only
```

`config/` is **gitignored** — it can contain secrets.

---

## 4. Offline vs online

| Capability | Offline | Online |
|---|---|---|
| Ray-traced physical lighting | ✅ | — |
| Text overlay / ageing | ✅ | ✅ |
| Bundled textures in `background/` | ✅ | ✅ |
| Your own images | ✅ | ✅ |
| AI texture generation | ❌ | needs token |
| NTP time sync | ❌ (system clock) | needs network |
| IP geolocation | ❌ | needs network |
| Live weather | ❌ (use presets) | needs network |

### Token (AI mode only)

Precedence, high → low:

1. `--token sk-xxxx`
2. environment variable `AGNES_API_TOKEN`
3. `api_token` in `config/token.json` (settings centre writes it, chmod 600)

TUI: `设置 → 凭据 → 设置 / 更换 API Token` (includes a connectivity test).

---

## 5. Platform notes

| Platform | Note |
|---|---|
| **Windows** | ANSI colour auto-degrades; `--no-color` also works |
| **macOS** | use Homebrew Python, the system one often lacks packages |
| **Linux** | without systemd the timezone falls back to `/etc/timezone` or `$TZ` |
| **Termux** | install `termux-api` for `termux-location` |
| **proot / container** | offline mode works without network; use `--set-location` |
| **low memory** | SSAA 8 on a 1312×736 texture allocates ~10k×6k grayscale (~60 MB); use `--ssaa 4` |

---

## 6. Reset

```bash
rm -rf output/     # renders only
rm -rf config/     # all user config (token, prompts, …)
python main.py --reset-config
```

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / macOS / Android `.so`, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
