# GoFindMe Mobile — Android app (self-contained, portrait)

This builds a standalone APK that bundles a Python runtime ([Chaquopy]) and runs
the full GoFindMe server (`uvicorn` on `127.0.0.1:8000`) inside the app, shown in
a **portrait-locked** WebView. No PC or separate server is needed.

The activity is fixed to portrait in two places — `android:screenOrientation="portrait"`
in `AndroidManifest.xml` and `setRequestedOrientation(...)` in `MainActivity` — so
the console always renders in the phone layout and never rotates mid-case.

## Scope (important)

On a phone there are **no external CLI tools** (sherlock, amass, the Go tools),
so the app runs the **API providers, encrypted vault, and the personal-footprint
data layer** — not the CLI tool-runner. Tool install/update is disabled
(`GOFINDME_ALLOW_TOOL_MGMT=0`). For the full tool-running experience, run the
server on a computer and point a browser/phone at it instead.

## Build differences vs. the server

- **pydantic v1** (v2's Rust `pydantic-core` can't build on Android). The app code
  is written to work under both v1 and v2.
- **pbkdf2_sha256** password hashing instead of argon2 (`app/security.py` falls
  back automatically when the argon2 backend is absent).
- **`cryptography`** comes from Chaquopy's prebuilt wheel.

## Getting the APK

The APK is built by GitHub Actions, not committed here. Push to `main` (or any
`claude/**` branch), or run the **Build Android APK** workflow manually: the run
uploads a `gofindme-mobile-debug-apk` artifact and publishes `gofindme-mobile.apk`
to the rolling `android-latest` release. Download and install it (enable "install
unknown apps" on the phone). It's a debug-signed APK.

## Building locally (optional)

Requires JDK 17 + Android SDK (+ NDK). From this `android/` dir:

```bash
# stage the Python sources the app bundles
mkdir -p app/src/main/python && cp -r ../app ../static ../legacy app/src/main/python/
gradle wrapper --gradle-version 8.7
./gradlew :app:assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

[Chaquopy]: https://chaquo.com/chaquopy/
