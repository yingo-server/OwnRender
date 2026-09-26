# Binary packages

> Built automatically by GitHub Actions with **Nuitka** on every push.
> Download from **Releases** (`nightly` = rolling build, `v*` = versioned).

---

## 1. What to download

| Platform | File |
|---|---|
| Windows x64 | `OwnRender-windows-x86_64.zip` |
| Windows x86 (32-bit) | `OwnRender-windows-x86.zip` |
| Windows arm64 | `OwnRender-windows-arm64.zip` |
| Linux x86_64 | `OwnRender-linux-x86_64.tar.gz` (glibc 2.35+) |
| Linux x86 (32-bit) | `OwnRender-linux-x86.tar.gz` (Debian 12 baseline) |
| Linux aarch64 | `OwnRender-linux-aarch64.tar.gz` |
| Linux armv7 (32-bit) | `OwnRender-linux-armv7.tar.gz` |
| Android arm64-v8a | `OwnRender-android-arm64-v8a-so.zip` — **`.so` libraries**, CLI/argument mode only (§5) |
| Android armeabi-v7a | `OwnRender-android-armeabi-v7a-so.zip` — 32-bit Android |
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

## 2. Desktop (Windows / Linux), all CPUs: identical to the script

```bash
# Linux (x86_64 / x86 / aarch64 / armv7)
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
| Windows | SmartScreen "unknown publisher" | More info → Run anyway |
| Linux | not executable | `chmod +x ownrender` |

Use a different asset/config root with `OWNRENDER_HOME=/path/to/dir ./ownrender`.

---

## 3. Geolocation on packaged builds

The binaries ship **no** location service; they call whatever the OS provides.

| Platform | Native GPS | Notes |
|---|---|---|
| Windows | Settings → Privacy → Location: allow apps | or `--ip-loc` / `--lat --lon` |
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
├── arm64-v8a/             (64-bit Android)
│   ├── libpython3.*.so    CPython runtime (built by python-for-android)
│   └── lib*.so            native deps (numpy/OpenBLAS/Pillow/OpenSSL, ...)
├── armeabi-v7a/           (32-bit Android, same layout)
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
The CI job is marked *best-effort* — if it fails, the other platform builds are
still released.

---

## 6. How CI works

`.github/workflows/build.yml`:

| Job | Contents |
|---|---|
| `linux-native` | matrix: `ubuntu-22.04` → **linux-x86_64**, `ubuntu-24.04-arm` → **linux-aarch64** |
| `linux-32bit` | matrix: **linux-x86** (native 32-bit inside a `debian:bookworm` i386 container), **linux-armv7** (`arm32v7/debian` + qemu, slow, `continue-on-error`) |
| `windows` | matrix: **windows-x86_64**, **windows-x86** (32-bit interpreter → 32-bit exe), **windows-arm64** (`windows-11-arm`, `continue-on-error`) |
| `android` | matrix: **arm64-v8a** / **armeabi-v7a**, python-for-android build → extract `.so` from the APK (`continue-on-error`) |
| `docs` | packs `README + docs/ + tools/` into `OwnRender-docs.zip` |
| `release` | aggregates artifacts → publishes to Releases (`always()`: whichever platform succeeded gets published) |

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

**Is there a macOS build?** No — Apple/macOS support has been dropped entirely.
Use the source version on macOS.

**Are there 32-bit builds?** Yes, four targets: `windows-x86`, `linux-x86`,
`linux-armv7` and `android-armeabi-v7a`.

**Are the artifacts updated automatically?** Yes. Every push to `main` rebuilds
and refreshes all platform packages, the Android `.so` sets and the docs bundle
in the `nightly` prerelease; pushing a `v*` tag publishes a stable release. This
document is embedded in the release body.

<!-- binaries-link -->
---

📦 **Binary packages** (Windows / Linux / Android `.so`; x86 / x86_64 / arm64 / armv7, built by CI with Nuitka) — **download & usage → [binaries.md](binaries.md)**
