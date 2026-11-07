"""Use a local Chromium browser without downloading anything at application startup."""
import os
import shutil
import sys
from pathlib import Path


def installed_browsers():
    candidates = []
    if sys.platform == 'win32':
        for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            root = os.environ.get(variable)
            if root:
                candidates.extend([
                    ('Microsoft Edge', Path(root) / 'Microsoft/Edge/Application/msedge.exe'),
                    ('Google Chrome', Path(root) / 'Google/Chrome/Application/chrome.exe'),
                ])
    elif sys.platform == 'darwin':
        for root in (Path('/Applications'), Path.home() / 'Applications'):
            candidates.extend([
                ('Google Chrome', root / 'Google Chrome.app/Contents/MacOS/Google Chrome'),
                ('Microsoft Edge', root / 'Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),
            ])
    for command in ('msedge', 'chrome', 'google-chrome', 'chromium', 'chromium-browser'):
        found = shutil.which(command)
        if found:
            candidates.append((command, Path(found)))
    seen = set()
    for label, path in candidates:
        key = str(path).lower() if sys.platform == 'win32' else str(path)
        if key not in seen and path.is_file():
            seen.add(key)
            yield label, str(path)


def browser_candidates(playwright):
    explicit = os.environ.get('TURBOWEB_CHROMIUM', '').strip().strip('"')
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise RuntimeError('TURBOWEB_CHROMIUM does not point to an existing browser executable: ' + str(path))
        # An explicit override is authoritative; do not silently select another browser.
        return [('Custom Chromium', str(path))]
    candidates = []
    bundled = Path(playwright.chromium.executable_path)
    if bundled.is_file():
        candidates.append(('Playwright Chromium', str(bundled)))
    candidates.extend(installed_browsers())
    return candidates


def launch_browser(playwright):
    candidates = browser_candidates(playwright)
    failures = []
    for label, executable in candidates:
        try:
            browser = playwright.chromium.launch(
                headless=True, executable_path=executable, args=['--disable-dev-shm-usage'])
            return browser, label
        except Exception as exc:
            failures.append(label + ': ' + str(exc).splitlines()[0][:250])
    guidance = (
        'No usable capture browser is available. Install Google Chrome or Microsoft Edge, '
        'or run "python -m playwright install chromium" if its download server is accessible. '
        'For a custom installation, set TURBOWEB_CHROMIUM to the full browser executable path. '
        'The application interface can still be used without a capture browser.'
    )
    if failures:
        guidance += ' Launch errors: ' + '; '.join(failures)
    raise RuntimeError(guidance)


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        candidates = browser_candidates(playwright)
        if not candidates:
            print('No local capture browser found. The app will still open.\n'
                  'Install Chrome/Edge before capturing, or install Playwright Chromium separately.')
            return 0
        for label, path in candidates:
            print(f'Browser found: {label} ({path})')
        print('No browser download is required. Browser launch is checked when capture starts.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
