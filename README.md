# TurboWebDownloader

**Your web, offline.** A local-first website archiver with a polished English HTML/CSS/JavaScript interface and a Python + Playwright capture engine. A native desktop window is available through pywebview.

![TurboWebDownloader mark](turboweb/static/logo.svg)

## What it does

- Opens a three-step project wizard on first launch (also available through **New project**).
- Renders pages in real Chromium, waits for dynamic content, and performs bounded scrolling for common lazy-loaded content.
- Follows same-domain page links, with configurable depth (0–10) and page budget (1–500).
- Collects selected stylesheets, images, fonts, JavaScript and media responses.
- Stores the rendered DOM, rewrites captured page/resource links and CSS references, and optionally formats HTML, CSS and JavaScript.
- Defaults to static snapshots: source JavaScript is saved if selected, but removed from the rendered page to avoid framework rehydration changing the snapshot. Experimental offline script execution is opt-in.
- Provides a persistent project library, search, filters, sorting, compact view, live activity logs, safe stop, capture-again, first-page screenshots and ZIP exports.
- Keeps project settings, a URL manifest and capture report on your own device.
- Includes original SVG/PNG/ICO branding and author details in **About the app**.

## Run locally

Requires **Python 3.11+**. Initial dependency/browser installation requires internet access; viewing captured content does not.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

Open **http://127.0.0.1:8080**. On Linux, install Chromium system dependencies if necessary:

```bash
python -m playwright install --with-deps chromium
```

For a native desktop window:

```bash
pip install -r requirements-desktop.txt
python desktop.py
```

Windows needs the Microsoft Edge WebView2 runtime (normally present on Windows 10/11). Linux pywebview needs a compatible GTK or Qt webview backend; see the pywebview installation documentation. Web mode works without pywebview.

### Windows quick start

With Python 3.11+ installed, double-click **`start-windows.bat`**. It prepares the virtual environment, installs the desktop dependencies and Chromium, and opens the native application. The first setup requires internet access. Alternatively, use the manual commands above.

### Automated Windows download

The **Validate and build** GitHub Actions workflow runs tests and creates a Windows x64 desktop distribution on pushes to the working branch and on pull requests. After a successful run, open the repository's **Actions** tab, select the run, and download **TurboWebDownloader-Windows-x64** under **Artifacts**. Extract the entire archive and launch `TurboWebDownloader.exe`. Artifacts expire after 14 days and require GitHub access; this is not a signed release or installer. A successful packaging job alone does not prove that the GUI has been manually tested on Windows.

### Windows EXE build

Run **`build-windows.bat` on Windows**. It creates a virtual environment, installs dependencies, downloads Chromium, generates the application icon and builds a windowed PyInstaller distribution:

```
dist/TurboWebDownloader/TurboWebDownloader.exe
```

**Distribute the entire `dist/TurboWebDownloader` directory**, including `_internal` and the bundled browser, not the EXE alone. This intentionally uses `--onedir` rather than a slow, large self-extracting single EXE. Chromium makes the distribution several hundred megabytes. Build on the Windows architecture you intend to support. This repository includes the build script, not a pre-built/signed executable. A Windows build has not been validated in this Linux workspace.

### Offline archives

Use **Browse offline** inside a completed project or **Export ZIP**. Extract the ZIP and open `index.html`. For best browser compatibility, serve the extracted folder locally:

```bash
python -m http.server 8081
```

Then open http://127.0.0.1:8081. Keep the `files` directory intact. All captured documents and resources use flat, deterministic filenames to avoid query-string collisions and simplify relative links. `manifest.json` maps original URLs to files. `report.json` records options, counts, warnings and errors.

Data is stored by default in **`~/.turbowebdownloader`**, outside the source tree. Set `TURBOWEB_DATA` to change it. Removing that folder deletes your local library. Preferences are stored in the UI browser's local storage. Interrupted captures are marked on restart; **Capture again** creates a fresh project rather than resuming a partially executed browser session.

## Scope and honest limitations

This is a rendered-page archiver, **not a clone of a site's backend**. It never retrieves server source code. There is no universal, pixel-identical archive for every modern website:

- Forms, payments, authenticated sessions, server search, WebSockets, API-driven interactions, DRM, canvas/WebGL, embedded cross-origin frames, blob URLs and streaming media may not work offline.
- Only pages reached through normal anchors within the configured depth/page limit are captured. This is not an automatic click-through tool for every SPA state. URL fragments are treated as anchors, not separate SPA routes.
- Chromium uses a fixed 1440 × 1000 viewport. Responsive layouts at other sizes, consent prompts, anti-bot pages and content with very long delays may differ.
- Lazy scrolling is bounded to four viewport heights. Offscreen/interaction-only resources might not be requested. Font/image loading failures can reduce fidelity.
- Selected scripts are downloaded, but arbitrary JavaScript URL strings, ES module imports and runtime API calls are not universally rewritten. Enabling scripts may change the saved DOM. Formatting is best-effort; HTML whitespace-sensitive content can change with prettification. Turn off readable source formatting when whitespace fidelity matters.
- Resources not captured (including excluded categories), links outside the capture, and unsupported URL references remain online. An archive is not guaranteed to make zero network requests; use disconnected browsing when that matters.
- There is a 25 MB per-resource / 500 MB total resource budget. Streaming/video and huge sites are intentionally constrained. Response-body limits are checked after buffering when no size header is supplied.
- One capture runs at a time, with up to five queued/running jobs. Stop is cooperative: an in-flight navigation can finish or time out before the archive is finalized. ZIP export is buffered in memory.
- No credentials, cookie import, login automation, paywall bypass, proxy rotation or CAPTCHA bypass are provided.

Only archive content you own or have permission to save, and follow site terms and copyright rules. Robots.txt is respected by default (page-level policy; resources are still subject to browser loading). The app identifies itself as TurboWebDownloader. If robots.txt cannot be fetched, a warning is logged; HTTP 401/403 stops the capture.

## Security / deployment

This is a **trusted, single-user local application**, not an authenticated multi-tenant service. Keep the default loopback binding for normal use. `python run.py --host 0.0.0.0 --port 8080` is provided for trusted development previews only: anyone able to reach it can inspect archives and start jobs. Do not expose it to the public internet.

Mutation requests require JSON and reject cross-origin Origin headers. Archive responses use CSP sandboxing without same-origin privileges; forms, frame embedding and fetch connections are restricted. This sandbox header is not present when you open exported files directly, so only enable offline script execution for trusted sites. Browser requests receive a public-address DNS check as a best-effort private-network guard; this is not a hardened network sandbox against hostile DNS rebinding/redirect behavior. Use OS/network isolation if capturing untrusted URLs.

## Development and checks

```bash
pip install pytest
python -m pytest -q
node --check turboweb/static/app.js
```

Tests cover settings validation, URL normalization/private-address checks, HTML/CSS rewriting, script policies, persistence recovery, cancellation, exports and archive isolation. Opt-in real-browser tests use a deterministic local fixture (the private-address guard is bypassed **only inside the test**) and verify offline navigation with HTTP(S) blocked, plus the wizard, preferences, About and mobile layout.

```bash
# Optional: use an already-installed Chromium executable
TURBOWEB_TEST_BROWSER=/path/to/chromium python -m pytest -q
```

`TURBOWEB_CHROMIUM=/path/to/chromium` also lets the application use an alternate Chromium executable. Normally, leave it unset and install Playwright's matched browser. Playwright's browser CDN is blocked in this Arena environment; validation used an alternate Chromium supplied through the permitted npm registry. See `TESTING.md` for exact validation status.

## Project structure

```
desktop.py               Native window entry point
run.py                   Local web server entry point
build-windows.bat        Windows EXE build recipe
scripts/make_icon.py     Dependency-free original ICO/PNG generator
turboweb/app.py          Local API, exports and sandboxed archive serving
turboweb/engine.py       Crawl queue, browser capture, persistence and rewriting
turboweb/templates/     English interface
turboweb/static/        Styles, animations, JavaScript and original branding
tests/                   Automated unit/API tests
```

## Author

**behnam ehsani**
[inbox.ehsani@gmail.com](mailto:inbox.ehsani@gmail.com)
[github.com/wrappedman/TurboWebDownloader](https://github.com/wrappedman/TurboWebDownloader)

## License

GPL-3.0; see [LICENSE](LICENSE). Dependencies and browser runtimes retain their own licenses.
