# Validation record

Validation date: 2026-11-07. Platform: Linux, Python 3.11, Node 22.

## Passed

- `python -m pytest -q`: 26 unit/API tests pass; three optional browser checks skip without an explicit executable.
- `LD_LIBRARY_PATH=/tmp/al2023/lib TURBOWEB_TEST_BROWSER=/tmp/chromium .venv/bin/python -m pytest -q`: **29 passed**.
- `node --check turboweb/static/app.js`: passed.
- `python -m compileall -q turboweb desktop.py run.py`: passed.
- `git diff --check`: passed.

Real-browser tests use a temporary Flask fixture with two linked pages, an external stylesheet, a stylesheet image and JavaScript that changes the rendered heading. They verify:

1. JavaScript-rendered text is saved in the HTML rather than just the initial server response.
2. Both linked pages, selected resources, screenshot, manifest and report are written.
3. CSS URLs and page links point to captured local files.
4. The archive can be opened and navigated while HTTP and HTTPS requests are blocked.
5. JavaScript still executes during capture even when script-file storage is disabled.
6. The first-launch wizard, step navigation, permission validation, author details, saved preferences and mobile width behavior work without JavaScript errors.

A desktop (1440px) and mobile (390px) screenshot were inspected during development. They are scratch artifacts, not committed application data. The live preview starts with an empty real workspace, not fabricated project records.

## Browser environment

The normal `python -m playwright install chromium` failed because outbound access to `cdn.playwright.dev` is unavailable here. For validation only, `@sparticuz/chromium` 153.0.0 was obtained from the permitted npm registry. Its bundled browser and runtime libraries were extracted to temporary paths. No browser payload or npm test dependency is committed. Production installs should use Playwright's matched Chromium via the documented installer.

The deterministic fixture deliberately bypasses the engine's private-address guard in the test process; ordinary application captures still reject private addresses. No external production website or authenticated site was used as an integration-test target. These tests are not proof of pixel-identical rendering on arbitrary websites.

## Not validated here

- Windows PyInstaller build or Windows WebView2 desktop launch (requires Windows).
- macOS / Linux native pywebview packaging.
- Arbitrary external-site compatibility, complex SPA interactions, authentication, streaming media or pixel-perfect equivalence.
- Security as a public internet service; this is a trusted local application.

The repository includes a Windows build BAT, not a pre-built or signed EXE.

## Follow-up: blocked browser downloads

Startup launchers no longer force a Playwright browser download. Added six tests covering installed Windows Edge discovery when Playwright Chromium is absent, bundled-browser priority, explicit paths with spaces/quotes, invalid overrides, no-browser diagnostics and launch-failure fallback. Discovery tests simulate Windows paths; they are not evidence of a real Windows desktop launch.

Latest validation: 34 unit/API/startup tests pass; 3 optional browser checks skip without an explicit executable. With the alternate local Chromium, all 37 tests pass (including the existing rendered capture and UI checks).

## Follow-up: exports, storage, image recovery and discovery

Latest suite: **55 passed** with a real alternate Chromium; without the browser override, **51 passed, 4 skipped**. New coverage includes browser ZIP downloads with archive-content checks, frontend native-export dispatch, a mocked native Save As dialog/cancellation, project storage paths, scan input validation, nested and gzipped sitemap parsing, exclusion of image-sitemap locations, redirect validation/disposal, transient resource retries, srcset/lazy resource discovery and extensionless CSS/font references. The real rendered fixture now verifies unrequested 2x image recovery, deep/lazy images, a transiently failing image, imported CSS, serialized CSSOM-injected styles and offline image rendering with HTTP(S) blocked. The actual preflight service is tested against the local sitemap fixture.

Native Save As is unit-tested with a mocked pywebview window; the actual Windows dialog still needs a Windows manual check. Public-site completeness and exact site totals are not guaranteed.

## Follow-up: URL-shaped layout and project deletion (1.2.0)

Latest complete run: **68 passed** with the alternate Chromium. Without an explicit test browser: **63 passed, 5 skipped**. Added filename/path tests for original names, extensionless pages, query variants, Windows reserved characters, path traversal, case/file-directory collisions and nested relative URL encoding. A two-origin browser fixture checks nested page/CSS/image/CDN directories, ZIP member paths and offline CSS/image/navigation with HTTP(S) blocked. Existing flat-layout export tests remain passing for compatibility.

Deletion tests cover keeping files across application restart, permanent removal and ZIP-cache cleanup, preservation of external ZIPs, invalid input, active/finalizing captures, and unknown project IDs. UI tests exercise cancellation, keep-files removal and permanent deletion through the actual confirmation dialog.
