# Binary packages

> Built automatically by GitHub Actions with **Nuitka** on every push.
> Download from **Releases** (`nightly` = rolling build, `v*` = versioned).

---

## 1. What to download

| Platform | File |
|---|---|
| Windows x64 | `OwnRender-windows-x86_64.zip` |
| Linux x86_64 | `OwnRender-linux-x86_64.tar.gz` (glibc 2.35+) |
| Linux aarch64 | `OwnRender-linux-aarch64.tar.gz` |
| macOS Apple Silicon | `OwnRender-macos-aarch64.tar.gz` (Intel Macs: use the source version) |
| Android | `OwnRender-android-arm64-v8a-so-*.zip` — **`.so` libraries**, CLI/argument mode only (§5) |
| Docs | `OwnRender-docs.zip` |

The extracted directory is **portable**:

```
OwnRender-linux-x86_64/
├── ownrender            the executable (ownrender.exe on Windows)
├── background/          material textures (replaceable)
├── fonts/               fonts (replaceable)
├── docs/                full documentation
├── README.md  LICENSE  CREDITS.md
└── RUN.txt              quick start
```

Assets are **not** baked into the binary — they sit next to it so you can swap
them. There is also a bundled fallback copy inside the binary.

---

## 2. Desktop (Windows / Linux / macOS): identical to the script

```bash
# Linux / macOS
tar -xzf OwnRender-linux-x86_64.tar.gz && cd OwnRender-linux-x86_64
chmod +x ownrender
./ownrender                       # TUI
```

```powershell
:: Windows
Expand-Archive OwnRender-windows-x86_64.zip
cd OwnRender-windows-x86_64
.\ownrender.exe                   # TUI
```

**Argument mode is exactly the same as `python main.py …`:**

```bash
./ownrender --offline-bg 微水泥 -y

./ownrender --offline-bg 微水泥 \
    --time "2025-06-21T09:00:00+08:00" \
    --lat 39.9042 --lon 116.4074 --weather clear -y

./ownrender --list-backgrounds
./ownrender --help
```

All flags, semantics, defaults and output filenames are identical to the source
version — see [cli.md](cli.md). The only difference: no Python install needed.

| Platform | First-run prompt | Fix |
|---|---|---|
| macOS | "cannot verify the developer" | `xattr -dr com.apple.quarantine ./ownrender` |
| Windows | SmartScreen "unknown publisher" | More info → Run anyway |
| Linux | not executable | `chmod +x ownrender` |

Use a different asset/config root with `OWNRENDER_HOME=/path/to/dir ./ownrender`.

---

## 3. Geolocation on packaged builds

The binaries ship **no** location service; they call whatever the OS provides.

| Platform | Native GPS | Notes |
|---|---|---|
| Windows | Settings → Privacy → Location: allow apps | or `--ip-loc` / `--lat --lon` |
| macOS | needs [`CoreLocationCLI`](https://github.com/fulldecent/corelocationcli) (`brew install corelocationcli`) and an approved location permission | CLI tools are often denied → use `--ip-loc` |
| Linux | GeoClue (`geoclue-2.0`), gpsd, ModemManager | timezone fallback is automatic |

Universal fallbacks:

```bash
./ownrender --offline-bg 微水泥 --lat 39.9042 --lon 116.4074 -y
./ownrender --set-location "39.9042,116.4074,北京"     # cache it
./ownrender --offline-bg 微水泥 --gps -y               # uses the cache
./ownrender --offline-bg 微水泥 --ip-loc -y
```

Diagnostics: TUI → `信息 → 定位测试` (environment, timezone, all 8 providers,
actual attempt, cache, IP services).

---

## 4. Replacing assets

```bash
cp my_wall.png OwnRender-linux-x86_64/background/
./ownrender --offline-bg my_wall -y

cp myfont.ttf OwnRender-linux-x86_64/fonts/
./ownrender --list-fonts
```

Font licensing: see [../../CREDITS.md](../../CREDITS.md).

---

## 5. Android (`.so` libraries, argument mode only)

```
android-so/
├── arm64-v8a/
│   ├── libpython3.*.so    CPython runtime (built by python-for-android)
│   └── libpybundle.so     this project's frozen Python modules
└── README.txt
```

**Why this shape**: Android has no official "standalone executable with an
embedded interpreter" path, and **Nuitka does not cross-compile to Android**.
The supported route is
[python-for-android](https://python-for-android.readthedocs.io/), which produces
the Python runtime + your code as shared libraries that a host app loads via JNI.

Usage (no TUI at all — argument mode only):

```java
Python py = Python.getInstance();
PyObject mod = py.getModule("main");
int code = mod.callAttr("run_args", new String[]{
        "--offline-bg", "微水泥", "-y"}).toInt();
```

```python
from main import run_args
run_args(["--offline-bg", "微水泥", "-y"])
```

- No arguments + non-interactive stdin → the program automatically switches to
  argument mode and prints `--help` (this path exists specifically for
  Android/embedded callers).
- Flags and outputs are identical to the desktop builds ([cli.md](cli.md)).
- **Location**: the host app must declare and hold `ACCESS_FINE_LOCATION`; the
  provider chain tries `termux-location` → `dumpsys/cmd location` → timezone
  fallback. Without permission, pass `--lat/--lon` or `--set-location`.
- Assets/output: point `OWNRENDER_HOME` at a writable directory; pass `-o` for
  the output directory.

**Known limitation**: these `.so` files must be used with the matching
python-for-android runtime; they cannot be `dlopen`ed into an arbitrary app.
The CI job is marked *best-effort* — if it fails, the three desktop builds are
still released.

---

## 6. How CI works

`.github/workflows/build.yml`:

| Job | Contents |
|---|---|
| `desktop` | matrix: `ubuntu-22.04` (x86_64), `ubuntu-24.04-arm` (aarch64), `windows-latest`, `macos-14` (Apple Silicon) → build → **binary smoke test incl. a real render** → upload |
| `android` | python-for-android build → extract `.so` from the APK (`continue-on-error`) |
| `docs` | packs `README + docs/ + tools/` into `OwnRender-docs.zip` |
| `release` | aggregates artifacts → publishes to Releases (push to `main` updates the rolling **nightly** prerelease; `v*` tags publish a versioned release) |

The smoke test is real: it renders an image with the packaged binary
(`--offline-bg 微水泥 --ssaa 2 -y`) to prove numpy/Pillow/fonts/assets all work
after freezing.

---

## 7. FAQ

**Same features as the source version?** Yes — the desktop binaries are the
frozen source, identical flags and outputs.

**Why are `background/` and `fonts/` next to the binary?** So you can replace
them. A bundled fallback copy exists inside the binary.

**Can I copy just the executable?** Yes; it falls back to the bundled assets.

**`GLIBC_2.xx not found` on Linux?** Build baseline is Ubuntu 22.04 (glibc 2.35)
— use the source version on older distros.

**Can the Android `.so` be used in Termux?** No — use the source version there.

**Is there a macOS (Intel) build?** No. Intel runners (`macos-13`) are retired
and queue indefinitely, so only Apple Silicon is published
(`OwnRender-macos-aarch64.tar.gz`). On an Intel Mac use the source version.

**Are the artifacts updated automatically?** Yes. Every push to `main` rebuilds
and refreshes the 4 desktop packages, the Android `.so` and the docs bundle
in the `nightly` prerelease; pushing a `v*` tag publishes a stable release. This
document is embedded in the release body.

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / macOS / Android `.so`, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
