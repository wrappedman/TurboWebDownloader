import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from .engine import ArchiveManager, DEFAULTS, normalize_url
from .exports import build_export
from .discovery import DiscoveryService


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
    root = Path(data_dir or os.environ.get('TURBOWEB_DATA', Path.home() / '.turbowebdownloader'))
    manager = ArchiveManager(root)
    root = manager.root
    app.extensions['archives'] = manager
    discovery = DiscoveryService(manager)
    app.extensions['discovery'] = discovery

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
            result = copy.deepcopy(list(manager.jobs.values()))
            for job in result:
                job['storage_path'] = str(root / job['id'])
                job['files_path'] = str(root / job['id'] / 'files')
            return jsonify(sorted(result, key=lambda p: p['created'], reverse=True))

    @app.post('/api/projects')
    def create():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(error='Expected a JSON object.'), 400
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
            result = copy.deepcopy(job)
            result['storage_path'] = str(root / job['id'])
            result['files_path'] = str(root / job['id'] / 'files')
            return jsonify(result), 201
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
        try:
            path = build_export(root, job)
            return send_file(path, mimetype='application/zip', as_attachment=True,
                             download_name='TurboWebDownloader-' + ident + '.zip', conditional=True)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        except OSError as exc:
            return jsonify(error='Could not create ZIP: ' + str(exc)), 500

    @app.get('/api/settings')
    def settings():
        return jsonify(storage_root=str(root), export_cache=str(root / '.exports'), native_desktop=app.config.get('NATIVE_DESKTOP', False))

    @app.post('/api/scans')
    def scan():
        data = request.get_json(silent=True)
        try:
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object.')
            url = normalize_url(str(data.get('url', '')))
            limit = data.get('limit', 50)
            depth = data.get('depth', 3)
            respect = data.get('respect_robots', True)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('Analysis page limit must be between 1 and 100.')
            if type(depth) is not int or not 0 <= depth <= 10:
                raise ValueError('Analysis depth must be between 0 and 10.')
            if not isinstance(respect, bool):
                raise ValueError('Invalid robots policy.')
            return jsonify(discovery.create(url, limit, depth, respect)), 202
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.get('/api/scans/<ident>')
    def scan_status(ident):
        try:
            return jsonify(discovery.snapshot(ident))
        except KeyError:
            abort(404)

    @app.post('/api/scans/<ident>/cancel')
    def scan_cancel(ident):
        with discovery.lock:
            if ident not in discovery.tasks:
                abort(404)
            discovery.tasks[ident]['event'].set()
        return jsonify(ok=True)

    return app
