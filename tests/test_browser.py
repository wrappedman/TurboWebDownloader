"""Opt-in real Chromium checks against a deterministic local fixture.

TURBOWEB_TEST_BROWSER=/path/to/chromium python -m pytest tests/test_browser.py -q
The private-network guard is bypassed ONLY for this in-process test fixture.
"""
import json
import os
import threading

import pytest
from flask import Flask, Response
from werkzeug.serving import make_server

from turboweb import engine

BROWSER = os.environ.get('TURBOWEB_TEST_BROWSER')
pytestmark = pytest.mark.skipif(not BROWSER, reason='Set TURBOWEB_TEST_BROWSER to opt into browser tests')


@pytest.mark.parametrize('store_scripts', [True, False])
def test_real_rendered_capture(tmp_path, monkeypatch, store_scripts):
    fixture = Flask('fixture')

    @fixture.get('/')
    def home():
        return '<!doctype html><html><head><link rel="stylesheet" href="/site.css"></head><body><h1>Fixture</h1><a href="/next">Next</a><script src="/app.js"></script></body></html>'

    @fixture.get('/next')
    def next_page():
        return '<!doctype html><h1>Second page</h1><a href="/">Home</a>'

    @fixture.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nAllow: /', mimetype='text/plain')

    @fixture.get('/site.css')
    def css():
        return Response('body{color:rgb(100,50,200);background-image:url("/dot.svg")}', mimetype='text/css')

    @fixture.get('/dot.svg')
    def image():
        return Response('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="white"/></svg>', mimetype='image/svg+xml')

    @fixture.get('/app.js')
    def js():
        return Response('document.querySelector("h1").textContent="Rendered by JavaScript";', mimetype='application/javascript')

    server = make_server('127.0.0.1', 0, fixture, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('TURBOWEB_CHROMIUM', BROWSER)
    monkeypatch.setattr(engine, 'public_url', lambda url: url)
    manager = engine.ArchiveManager(tmp_path)
    url = f'http://127.0.0.1:{server.server_port}/'
    job = dict(id='fixture', name='Fixture', url=url, options={**engine.DEFAULTS, 'depth':1, 'delay':0, 'max_pages':2, 'scripts':store_scripts}, status='queued',created=0,pages=0,assets=0,bytes=0,failed=0,logs=[],message='',entry=None)
    manager.jobs['fixture'] = job
    manager.cancel_events['fixture'] = threading.Event()
    try:
        manager.run(job)
        assert job['status'] == 'completed', job['logs']
        assert job['pages'] == 2
        assert job['assets'] >= (3 if store_scripts else 2)
        folder = tmp_path/'fixture'
        manifest = json.loads((folder/'manifest.json').read_text())
        assert (url+'app.js' in manifest['urls']) == store_scripts
        first = (folder/'files'/job['entry']).read_text()
        assert 'Rendered by JavaScript' in first
        assert '<script' not in first
        assert manifest['urls'][url+'next'] in first
        css_text = (folder/'files'/manifest['urls'][url+'site.css']).read_text()
        assert manifest['urls'][url+'dot.svg'] in css_text
        assert (folder/'preview.png').exists()
        assert (folder/'report.json').exists()
        # Open the resulting archive with all HTTP(S) requests blocked.
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER, headless=True)
            page = browser.new_page()
            page.route('http://**/*', lambda route: route.abort())
            page.route('https://**/*', lambda route: route.abort())
            page.goto((folder/'index.html').as_uri())
            assert page.locator('h1').inner_text() == 'Rendered by JavaScript'
            page.get_by_role('link', name='Next').click()
            assert page.locator('h1').inner_text() == 'Second page'
            browser.close()
    finally:
        server.shutdown()
