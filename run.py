"""Web mode: python run.py --host 0.0.0.0 --port 8080"""
import argparse
from turboweb.app import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TurboWebDownloader local application')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8080, type=int)
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port, threaded=True, debug=False)
