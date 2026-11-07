"""Native application and a non-GUI packaged-distribution self-test."""
import json
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path


def prepare_environment():
    if getattr(sys, 'frozen', False):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(sys._MEIPASS) / 'browsers')


def packaged_self_test(report_path):
    result = {'ok': False}
    try:
        prepare_environment()
        import webview  # noqa: F401 -- verify packaged WebView/pythonnet dependencies
        if sys.platform == 'win32':
            import clr  # noqa: F401
        from turboweb.app import create_app
        from turboweb.native import DesktopAPI  # noqa: F401
        from turboweb.browser import launch_browser
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='turboweb-self-test-') as data:
            app = create_app(data)
            client = app.test_client()
            if client.get('/').status_code != 200 or client.get('/static/logo.svg').status_code != 200:
                raise RuntimeError('Packaged templates or static assets are missing.')
            with sync_playwright() as p:
                browser, label = launch_browser(p)
                try:
                    page = browser.new_page()
                    page.set_content('<title>TurboWebDownloader self-test</title>')
                    if page.title() != 'TurboWebDownloader self-test':
                        raise RuntimeError('Capture browser failed to render the self-test page.')
                    result.update(ok=True, browser=label)
                finally:
                    browser.close()
    except Exception:
        result['error'] = traceback.format_exc()
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def main():
    prepare_environment()
    import webview
    from werkzeug.serving import make_server
    from turboweb.app import create_app
    from turboweb.native import DesktopAPI
    app = create_app()
    app.config['NATIVE_DESKTOP'] = True
    bridge = DesktopAPI(app.extensions['archives'])
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    window = webview.create_window('TurboWebDownloader', f'http://127.0.0.1:{server.server_port}', width=1440, height=940, min_size=(1000, 700), background_color='#f5f7fb', js_api=bridge)
    bridge._window = window
    try:
        webview.start()
    finally:
        server.shutdown()
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        raise SystemExit(packaged_self_test(sys.argv[2]))
    raise SystemExit(main())
