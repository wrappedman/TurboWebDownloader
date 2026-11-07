"""Opt-in real Chromium checks against a deterministic local fixture.

TURBOWEB_TEST_BROWSER=/path/to/chromium python -m pytest tests/test_browser.py -q
The private-network guard is bypassed ONLY for this in-process test fixture.
"""
import json
import os
import threading
import time

import pytest
from flask import Flask, Response
from werkzeug.serving import make_server

from turboweb import engine
from turboweb.paths import relative_url

BROWSER = os.environ.get('TURBOWEB_TEST_BROWSER')
pytestmark = pytest.mark.skipif(not BROWSER, reason='Set TURBOWEB_TEST_BROWSER to opt into browser tests')


@pytest.mark.parametrize('store_scripts', [True, False])
def test_real_rendered_capture(tmp_path, monkeypatch, store_scripts):
    fixture = Flask('fixture')

    @fixture.get('/')
    def home():
        return '<!doctype html><html><head><link rel="stylesheet" href="/site.css"></head><body><h1>Fixture</h1><a href="/next">Next</a><img id="lazy" data-src="/lazy.svg"><img id="responsive" src="/dot.svg" srcset="/dot.svg 1x, /two.svg 2x"><img id="retry" src="/retry.svg"><img id="deep" loading="lazy" src="/far.svg" style="margin-top:7000px"><script src="/app.js"></script></body></html>'

    @fixture.get('/next')
    def next_page():
        return '<!doctype html><h1>Second page</h1><a href="/">Home</a>'

    @fixture.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nAllow: /', mimetype='text/plain')

    @fixture.get('/site.css')
    def css():
        return Response('@import "/theme.css"; body{color:rgb(100,50,200);background-image:url("/dot.svg")}', mimetype='text/css')

    @fixture.get('/lazy.svg')
    @fixture.get('/two.svg')
    @fixture.get('/far.svg')
    @fixture.get('/dot.svg')
    def image():
        return Response('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="white"/></svg>', mimetype='image/svg+xml')

    @fixture.get('/app.js')
    def js():
        return Response('document.querySelector("h1").textContent="Rendered by JavaScript";const s=document.createElement("style");document.head.append(s);s.sheet.insertRule("h1{border-top:3px solid red}");', mimetype='application/javascript')

    @fixture.get('/sitemap.xml')
    def sitemap():
        return Response('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>/pages.xml</loc></sitemap></sitemapindex>', mimetype='application/xml')

    @fixture.get('/pages.xml')
    def sitemap_pages():
        return Response('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/</loc></url><url><loc>/next</loc></url><url><loc>/unlinked</loc></url></urlset>', mimetype='application/xml')

    @fixture.get('/theme.css')
    def imported_css():
        return Response('h1{background-image:url(/two.svg)}', mimetype='text/css')

    retries = [0]
    @fixture.get('/retry.svg')
    def transient_image():
        retries[0] += 1
        if retries[0] <= 2:
            return Response('transient', status=503)
        return image()

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
        assert job['discovered'] >= 3
        for resource in ('lazy.svg','two.svg','far.svg','retry.svg','theme.css'):
            assert url+resource in manifest['urls'], (resource, job['logs'])
        assert job['failed_assets'] == 0
        assert (url+'app.js' in manifest['urls']) == store_scripts
        first = (folder/'files'/job['entry']).read_text()
        assert 'Rendered by JavaScript' in first
        assert 'border-top' in first
        assert '<script' not in first
        assert relative_url(manifest['urls'][url+'next'], job['entry']) in first
        css_text = (folder/'files'/manifest['urls'][url+'site.css']).read_text()
        assert relative_url(manifest['urls'][url+'dot.svg'], manifest['urls'][url+'site.css']) in css_text
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
            page.wait_for_function("getComputedStyle(document.querySelector('h1')).borderTopWidth === '3px'")
            page.wait_for_function("document.querySelector('#lazy').complete && document.querySelector('#lazy').naturalWidth > 0")
            page.wait_for_function("document.querySelector('#deep').complete && document.querySelector('#deep').naturalWidth > 0")
            page.get_by_role('link', name='Next').click()
            assert page.locator('h1').inner_text() == 'Second page'
            browser.close()
        if store_scripts:
            from turboweb.discovery import DiscoveryService
            discovery = DiscoveryService(manager)
            result = discovery.create(url, limit=2, depth=1)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                result = discovery.snapshot(result['id'])
                if result['status'] not in ('queued','running'):
                    break
                time.sleep(.1)
            assert result['status'] == 'completed', result
            assert result['sitemap_count'] == 3
            assert result['discovered'] >= 3
            assert result['inspected'] <= 2
    finally:
        server.shutdown()
