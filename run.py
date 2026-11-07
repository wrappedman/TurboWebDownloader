"""Web mode: python run.py --host 0.0.0.0 --port 8080."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description='TurboWebDownloader local application')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8080, type=int)
    args = parser.parse_args()
    try:
        from turboweb.app import create_app
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith('turboweb'):
            raise
        print(
            f'TurboWebDownloader cannot start: missing Python dependency "{exc.name}".\n'
            f'Python interpreter: {sys.executable}\n\n'
            'Run these commands from the project directory:\n'
            f'  "{sys.executable}" -m pip install -r requirements.txt\n'
            f'  "{sys.executable}" -m playwright install chromium\n'
            f'  "{sys.executable}" run.py\n\n'
            'On Windows you can instead double-click start-web-windows.bat\n'
            'to set up an isolated environment and start web mode.',
            file=sys.stderr,
        )
        return 1
    create_app().run(host=args.host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
