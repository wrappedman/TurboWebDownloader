import copy
import io
import os
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from .engine import ArchiveManager, DEFAULTS, normalize_url


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
    root = Path(data_dir or os.environ.get('TURBOWEB_DATA', Path.home() / '.turbowebdownloader'))
    manager = ArchiveManager(root)
    app.extensions['archives'] = manager

    @app.before_request
    def protect_mutations():
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('Origin')
            if origin and urlsplit(origin).netloc != request.host:
                abort(403)
            if not request.is_json:
                return jsonify(error='JSON request required.'), 415

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.path.startswith('/archive/'):
            # Archived website code never gets access to the application's origin.
            response.headers['Content-Security-Policy'] = "sandbox allow-scripts; object-src 'none'; frame-src 'none'; connect-src 'none'; form-action 'none'"
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/projects')
    def projects():
        with manager.lock:
            return jsonify(sorted(copy.deepcopy(list(manager.jobs.values())), key=lambda p: p['created'], reverse=True))

    @app.post('/api/projects')
    def create():
        data = request.get_json(silent=True) or {}
        try:
            name = str(data.get('name', '')).strip()[:80]
            if not name:
                raise ValueError('Give your project a name.')
            url = normalize_url(str(data.get('url', '')))
            supplied = data.get('options', {})
            if not isinstance(supplied, dict):
                raise ValueError('Invalid options.')
            options = DEFAULTS.copy()
            for key, default in DEFAULTS.items():
                if key not in supplied:
                    continue
                value = supplied[key]
                if isinstance(default, bool):
                    if not isinstance(value, bool):
                        raise ValueError('Invalid option: ' + key)
                elif type(value) is not int:
                    raise ValueError('Invalid number: ' + key)
                options[key] = value
            for key, low, high in [('max_pages', 1, 500), ('depth', 0, 10), ('delay', 0, 10000), ('timeout', 5000, 90000)]:
                if not low <= options[key] <= high:
                    raise ValueError(f'{key} must be between {low} and {high}.')
            with manager.lock:
                if sum(j['status'] in ('queued', 'running', 'stopping') for j in manager.jobs.values()) >= 5:
                    return jsonify(error='The queue is full. Wait for a capture to finish.'), 409
            job = manager.create(name, url, options)
            return jsonify(copy.deepcopy(job)), 201
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400

    def get_job(ident):
        if ident not in manager.jobs:
            abort(404)
        return manager.jobs[ident]

    @app.post('/api/projects/<ident>/cancel')
    def cancel(ident):
        job = get_job(ident)
        with manager.lock:
            if job['status'] in ('queued', 'running'):
                manager.cancel_events[ident].set()
                manager.update(job, status='stopping', message='Stopping safely…')
        return jsonify(ok=True)

    @app.get('/archive/<ident>/<path:filename>')
    def archive(ident, filename):
        get_job(ident)
        return send_from_directory(root / ident, filename)

    @app.get('/api/projects/<ident>/export')
    def export(ident):
        job = get_job(ident)
        if job['status'] in ('queued', 'running', 'stopping') or not job['entry']:
            return jsonify(error='Wait for a finished capture before exporting.'), 409
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in (root / ident).rglob('*'):
                if file.is_file() and file.name != 'project.json':
                    archive.write(file, file.relative_to(root / ident))
            archive.writestr('READ ME.txt', 'TurboWebDownloader offline archive\nOpen index.html in a browser. For best compatibility, serve this folder with: python -m http.server 8080\nOnly captured pages and resources work offline. Forms, APIs, logins and uncaptured links may require the original website.\n')
        buffer.seek(0)
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name='TurboWebDownloader-' + ident + '.zip')

    return app
