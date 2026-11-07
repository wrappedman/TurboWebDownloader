"""Native window; server is bound only to loopback with an OS-assigned port."""
import os
import sys
import threading
from pathlib import Path

if __name__ == '__main__':
    import webview
    from werkzeug.serving import make_server
    from turboweb.app import create_app
    from turboweb.native import DesktopAPI
    if getattr(sys, 'frozen', False):
        # The build includes the Playwright browser payload beside the executable.
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(sys._MEIPASS) / 'browsers')
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
