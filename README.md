# TurboWebDownloader

**Your web, offline.** A local-first website archiver with a polished English HTML/CSS/JavaScript interface and a Python + Playwright capture engine. A native desktop window is available through pywebview.

![TurboWebDownloader mark](turboweb/static/logo.svg)

## What it does

- Opens a three-step project wizard on first launch (also available through **New project**).
- Renders pages in real Chromium, waits for dynamic content, and performs bounded scrolling for common lazy-loaded content.
- Follows same-domain page links, with configurable depth (0–10) and page budget (1–500).
- Collects selected stylesheets, images, fonts, JavaScript and media responses, then recovers missing DOM resources, responsive image candidates and recursive CSS imports/fonts/backgrounds with bounded retries.
- Analyzes nested/gzipped sitemaps and rendered links before capture, displaying known URL counts, inspected pages, warnings and an option to use the discovered count as the page limit.
- Shows the absolute storage location for each project, with Copy path and native Open folder controls. Native ZIP export uses a Save As dialog; web mode uses browser downloads.
- Stores the rendered DOM, rewrites captured page/resource links and CSS references, and optionally formats HTML, CSS and JavaScript.
- Defaults to static snapshots: source JavaScript is saved if selected, but removed from the rendered page to avoid framework rehydration changing the snapshot. Experimental offline script execution is opt-in.
- Provides a persistent project library, search, filters, sorting, compact view, live activity logs, safe stop, capture-again, first-page screenshots and ZIP exports.
- Keeps project settings, a URL manifest and capture report on your own device.
- Includes original SVG/PNG/ICO branding and author details in **About the app**.

## Run locally

Requires **Python 3.11+**. Initial Python dependency installation requires internet access; viewing captured content does not. Capture can use an installed Chrome/Edge or a separately installed Playwright Chromium.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

python -m pip install -r requirements.txt
# Optional if Chrome/Edge is not installed:
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

For the web interface, double-click **`start-web-windows.bat`**. It uses the Python available on your system, creates `.venv`, installs the web dependencies, detects an existing browser, and starts the local server. It does not download Chromium or block startup when no capture browser is found. Then open **http://127.0.0.1:8080**. Keep the console open.

If you prefer Windows CMD commands (no environment activation required):

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe run.py
```

**`ModuleNotFoundError: No module named 'flask'`** means the Python running the application does not have its dependencies installed. Use the explicit `.venv\Scripts\python.exe` commands above for both installation and execution; installing into a different Python environment will not fix it. Do not install only Flask: `requirements.txt` contains the other required packages too.

With Python 3.11+ installed, double-click **`start-windows.bat`**. It prepares the virtual environment, installs the desktop dependencies, detects an existing browser, and opens the native application without downloading Chromium. The first setup requires internet access. Alternatively, use the manual commands above.

### Chromium download blocked (403 / location restriction)

A successful pip installation followed by `not available in your location` is a browser CDN restriction, not a Flask or Python installation error. Updated startup BAT files no longer require that download. The capture engine tries:

1. `TURBOWEB_CHROMIUM`, when explicitly set (must be a valid executable path).
2. Playwright's installed/bundled Chromium.
3. Existing Microsoft Edge or Google Chrome in standard system/user installation folders, then Chromium-family browsers found on PATH.

The UI can open with no browser available, but a new capture will report an actionable error until one is available. System browsers are launched with a separate temporary profile; this does not import your normal logged-in browser session. Browser versions and enterprise policies can affect automation compatibility.

For example, in Windows CMD, **if this executable exists**:

```bat
set "TURBOWEB_CHROMIUM=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
.venv\Scripts\python.exe run.py
```

Or launch `.venv\Scripts\python.exe desktop.py` from the same CMD window. Chrome is commonly installed at `C:\Program Files\Google\Chrome\Application\chrome.exe`. Use the actual installed path, not a guessed one. Run `.venv\Scripts\python.exe -m turboweb.browser` to list detected browsers without downloading anything.

### Automated Windows download

The **Validate and build** GitHub Actions workflow runs tests and creates a Windows x64 desktop distribution on pushes to the working branch and on pull requests. After a successful run, open the repository's **Actions** tab, select the run, and download **TurboWebDownloader-Windows-x64** under **Artifacts**. Extract the entire archive and launch `TurboWebDownloader.exe`. Artifacts expire after 14 days and require GitHub access; this is not a signed release or installer. A successful packaging job alone does not prove that the GUI has been manually tested on Windows.

### Windows EXE build

Run **`build-windows.bat` on Windows**. It creates a virtual environment, installs dependencies, downloads Chromium, generates the application icon and builds a windowed PyInstaller distribution:

```
dist/TurboWebDownloader/TurboWebDownloader.exe
```

**Distribute the entire `dist/TurboWebDownloader` directory**, including `_internal` and the bundled browser, not the EXE alone. This intentionally uses `--onedir` rather than a slow, large self-extracting single EXE. Chromium makes the distribution several hundred megabytes. Build on the Windows architecture you intend to support. This repository includes the build script, not a pre-built/signed executable. A Windows build has not been validated in this Linux workspace.

### Offline archives

Use **Browse offline** inside a completed project or **Save as ZIP**. Desktop mode opens a native Save As dialog and confirms the chosen path. Web mode downloads to your browser's configured location. ZIPs are built on disk under the data directory's `.exports` cache, rather than buffering the full archive in RAM. Extract the ZIP and open `index.html`. For best browser compatibility, serve the extracted folder locally:

```bash
python -m http.server 8081
```

Then open http://127.0.0.1:8081. Keep the `files` directory intact. New captures preserve URL folder paths and original static filenames inside a separate folder per host. HTML/CSS links are rewritten relative to each saved file; ZIP exports preserve the same directory tree. `manifest.json` maps original URLs to files. `report.json` records options, counts, warnings and errors. `missing-resources.json` lists resource URLs and reasons still failing after recovery. Re-capture older projects to benefit from the improved resource collection.

Data is stored by default in **`~/.turbowebdownloader`**, outside the source tree. Set `TURBOWEB_DATA` to change it. Removing that folder deletes your local library. Preferences are stored in the UI browser's local storage. Interrupted captures are marked on restart; **Capture again** creates a fresh project rather than resuming a partially executed browser session.

### Website-shaped filenames and directories (1.2.0)

New captures use the URL-visible structure, not hashed filenames:

```text
<project-id>/
  index.html                         # Opens the captured entry page
  manifest.json
  report.json
  project.json                       # Local application metadata; excluded from ZIP
  files/
    example.com/
      index.html
      docs/
        guide.html
        tutorial/index.html
      assets/css/style.css
      images/logo.png
    cdn.example.com/
      fonts/brand.woff2
```

- `/assets/css/style.css` and `/images/logo.png` keep their names and folder paths.
- Extensionless page routes like `/docs/tutorial` and directory URLs become `docs/tutorial/index.html`. Server-side page names such as `view.php` become `view.php.html` because the archive contains rendered HTML, not runnable server code.
- Query variants get a short `__q_…` suffix so `photo.jpg?w=400` does not overwrite `photo.jpg?w=800`.
- Windows-reserved/invalid names are made safe. Case-insensitive name collisions, file/directory conflicts, HTTP/HTTPS duplicates and route collisions get short disambiguating suffixes. Extremely long paths use a `_longpaths` fallback. These are exceptions to exact naming, necessary for portable filesystem output.
- Each captured HTML/CSS file uses relative links appropriate to its own directory, including cross-host resources. `manifest.json` maps original URLs to the saved filesystem paths.
- This mirrors **public URLs**, not the site's private server filesystem or backend architecture.

Old archives remain readable/exportable in their existing layout. **Capture again** is required for the new layout; existing files are not silently renamed or migrated.

### Deleting projects

Open a finished project's details and choose **Delete project**. The confirmation asks whether downloaded files should also be deleted:

- **Keep downloaded files** (default): removes the project from the library and marks its metadata as hidden. The archive stays at the displayed path and will not reappear after restart. Open its `index.html` directly or serve the folder locally. There is no automatic re-import UI.
- **Delete project and downloaded files**: permanently removes the project folder and its application-managed cached ZIP. ZIP copies saved elsewhere are not removed. This operation cannot be undone.

Running/queued captures must first be stopped and allowed to finish finalization. Canceling the deletion dialog makes no changes.

### Storage location and preflight analysis

On Windows the default project path is `%USERPROFILE%\.turbowebdownloader\<project-id>`. The exact resolved path is shown in the project panel and the root folder in Preferences. `files` contains the captured HTML/resources; the parent folder contains `index.html`, reports and the screenshot. To use a different root, set `TURBOWEB_DATA` before launch (existing projects are not automatically moved):

```bat
set "TURBOWEB_DATA=D:\WebArchives"
.venv\Scripts\python.exe desktop.py
```

The wizard starts analysis when you enter Capture settings. You can stop it, refresh it, or use the discovered count (capped at the supported 500-page capture limit). Analysis inspects up to 10/50/100 pages, depth 3, plus up to 20 sitemap files and 10,000 sitemap URLs. Sitemap traversal has a 30-second scheduling budget (an in-flight request can finish afterward); rendered inspection has a 2-minute budget. Analysis and capture share the single browser-work queue. Counts may be partial, sitemaps may be stale, and unreachable/private/interaction-only pages cannot be counted reliably. **Known URLs are not a verified total of all pages.** Capture still respects its selected depth/page limit and robots policy; discovered does not mean successfully archived.

## Scope and honest limitations

This is a rendered-page archiver, **not a clone of a site's backend**. It never retrieves server source code. There is no universal, pixel-identical archive for every modern website:

- Forms, payments, authenticated sessions, server search, WebSockets, API-driven interactions, DRM, canvas/WebGL, embedded cross-origin frames, blob URLs and streaming media may not work offline.
- Pages are discovered through normal anchors and, when enabled at depth 1+, sitemaps, within the configured depth/page limit. This is not an automatic click-through tool for every SPA state. URL fragments are treated as anchors, not separate SPA routes.
- Chromium uses a fixed 1440 × 1000 viewport. Responsive layouts at other sizes, consent prompts, anti-bot pages and content with very long delays may differ.
- Lazy scrolling is bounded to 40 scroll steps and waits for bottom stability; common lazy attributes are promoted and selected images/fonts are awaited. Resource recovery also inspects DOM references, responsive candidates and stylesheet dependencies. Infinite feeds, unusual custom loaders, inaccessible CDN resources and interaction-only states may still be incomplete; failed recovery URLs appear in `missing-resources.json`. CSS-in-JS style rules are serialized when accessible.
- Selected scripts are downloaded, but arbitrary JavaScript URL strings, ES module imports and runtime API calls are not universally rewritten. Enabling scripts may change the saved DOM. Formatting is best-effort; HTML whitespace-sensitive content can change with prettification. Turn off readable source formatting when whitespace fidelity matters.
- Resources not captured (including excluded categories), links outside the capture, and unsupported URL references remain online. An archive is not guaranteed to make zero network requests; use disconnected browsing when that matters.
- There is a 25 MB per-resource / 500 MB total resource budget. Streaming/video and huge sites are intentionally constrained. Response-body limits are checked after buffering when no size header is supplied.
- One capture runs at a time, with up to five queued/running jobs. Stop is cooperative: an in-flight navigation can finish or time out before the archive is finalized. ZIP exports are disk-backed and cached; ensure adequate free disk space for both the archive and ZIP.
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
turboweb/discovery.py    Preflight URL discovery through sitemaps/rendered links
turboweb/capture_tools.py Lazy preparation, resource discovery and retry requests
turboweb/exports.py      Disk-backed ZIP generation
turboweb/paths.py        Website-shaped filenames, relative links, collision safety
turboweb/native.py       Desktop Save As / Open folder bridge
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
