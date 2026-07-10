# GoFindMe Mobile — Portrait Edition

A **portrait-optimized, phone-first build** of the
[GoFindMe](https://github.com/ether4o4/GoFindMe) self-hosted OSINT / DFIR
investigations console. It packages the full FastAPI server into a single
Android APK (via [Chaquopy]) and shows it in a **portrait-locked WebView**, so
the whole console runs on the phone with nothing else to install.

> ⚠️ **Authorized use only.** GoFindMe queries third-party data providers on
> your behalf. Use it only for investigations you are legally authorized to
> conduct, and follow each upstream service's terms of use.

---

## Two ways to run it

On first launch the app shows a **connection screen** with two choices:

1. **Connect to my server (recommended)** — point the app at a GoFindMe server
   running on your **PC or VPS** and use the phone as a pure dashboard. The PC
   runs the real CLI tools (sherlock, amass, …) and holds your API keys; the
   phone just shows the console. **To reach it when you're not on the same
   Wi-Fi**, put the PC on a private tunnel — **[Tailscale](https://tailscale.com)**
   is the easy, free way: install it on the PC and phone, run
   `sudo tailscale serve --bg 8000` on the PC, and paste the resulting
   `https://<machine>.tailXXXX.ts.net` URL into the app. No port-forwarding, no
   public exposure, works over cellular. (A VPS with an HTTPS address works too.)
2. **Run on this phone** — the self-contained bundled server (API providers,
   encrypted vault, personal-footprint data layer). No CLI tools — those can't
   run on Android — so username/name searches come back empty here; it's most
   useful once you add API keys under **Sources**.

Long-press the **Back** button anytime to return to the connection screen and
switch servers. The chosen server is remembered between launches.

> Reaching a home PC from anywhere genuinely requires a tunnel or public host —
> a phone on cellular can't otherwise see your LAN. Tailscale is the simplest;
> the app itself just loads whatever URL you give it.

## What makes this the "mobile" edition

This repo is a downstream, phone-tuned variant of GoFindMe. The backend, vault,
and data layer are unchanged; the difference is the presentation and packaging:

- **Portrait-locked app.** The Android activity is fixed to portrait
  (`android:screenOrientation="portrait"` + a runtime lock in `MainActivity`),
  so the console always renders in its phone layout and never rotates mid-case.
- **Portrait-first UI.** The dashboard CSS is retuned for tall, narrow screens:
  a thumb-reach bottom nav, 44px tap targets, notch/safe-area insets, stat tiles
  that pair two-across, a shorter relationship-graph canvas, an inspector that
  slides up as a **bottom sheet**, and modals that dock to the bottom as sheets.
- **Full-screen web-app chrome.** `index.html` ships the mobile-web-app meta
  tags so it also behaves as a standalone portrait web app if you "Add to Home
  Screen" instead of installing the APK.

Everything else — encrypted API vault, personal-footprint data layer, cases,
reports, audit trail — works exactly as it does upstream.

### New: case file attachments

Each investigation has a **Files** tab where you can attach evidence files
(screenshots, exports, documents) straight from the phone — tap to pick or drag
to drop. Every upload is SHA-256 fingerprinted, stored server-side under the case
(one folder per case, with a generated on-disk name so the original filename
never touches the filesystem path), and **shown as a node on the case
relationship graph** linked to the subject. Files can be downloaded or deleted,
count toward the case totals, and are removed from disk when the case is deleted.
Per-file size cap is configurable via `GOFINDME_MAX_UPLOAD_MB` (default 25).

### Scope on a phone

There are **no external CLI tools** (sherlock, amass, the Go tools) on a phone,
so the app runs the **API providers, encrypted vault, and personal-footprint
data layer** — not the CLI tool-runner. Tool install/update is disabled
(`GOFINDME_ALLOW_TOOL_MGMT=0`). For the full tool-running experience, run the
upstream server on a computer/VPS and point this phone's browser at it instead.

---

## Get the APK

The APK is built by GitHub Actions, not committed here. Once a build has run on
this repo, the latest debug-signed APK is always at the rolling release:

**➡ https://github.com/ether4o4/gofindme_mobile/releases/tag/android-latest**
(asset: `gofindme-mobile.apk`)

To build/refresh it:

- Push to `main` (or any `claude/**` branch) touching `android/`, `app/`,
  `static/`, or `legacy/`, **or**
- Run the **Build Android APK** workflow manually (Actions → *Build Android APK*
  → *Run workflow*).

Then on the phone: enable **"install unknown apps"** for your browser/files app
and open the downloaded `gofindme-mobile.apk`. It's debug-signed.

---

## Building the APK locally (optional)

Requires JDK 17 + Android SDK (+ NDK). From the repo root:

```bash
# stage the Python sources the app bundles
mkdir -p android/app/src/main/python
cp -r app static legacy android/app/src/main/python/
cd android
gradle wrapper --gradle-version 8.7
./gradlew :app:assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

Build notes (same as upstream Android build): **pydantic v1** (v2's Rust core
won't build on Android), **pbkdf2_sha256** password hashing fallback, and
`cryptography` from Chaquopy's prebuilt wheel. See `android/README.md`.

---

## Run the server directly (desktop/dev)

The Python server is a normal FastAPI app, so you can also run it without
Android to preview the portrait UI in a browser (use your browser's device
toolbar in portrait):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./run.sh                      # serves http://127.0.0.1:8000
```

---

## Layout

| Path | Purpose |
|------|---------|
| `app/` | FastAPI backend (auth, vault, providers, cases, data, reports) |
| `static/` | The portrait-optimized dashboard (`index.html`, `css/`, `js/`) |
| `android/` | Chaquopy Android wrapper — **portrait-locked** WebView shell |
| `legacy/` | The original single-file launcher, served at `/legacy` |
| `.github/workflows/android.yml` | Builds the APK and publishes it to the release |

---

## Upstream

This is a mobile fork of **[ether4o4/GoFindMe](https://github.com/ether4o4/GoFindMe)**.
For the full desktop/VPS experience, tool-runner, and documentation
(security whitepaper, deployment, data handling), see the upstream repo.

[Chaquopy]: https://chaquo.com/chaquopy/
