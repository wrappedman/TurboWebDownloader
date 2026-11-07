"""End-to-end URL-shaped files and links, including a second resource origin."""
import json
import os
import threading
import zipfile
from urllib.parse import urlsplit

import pytest
from flask import Flask, Response
from werkzeug.serving import make_server

from turboweb import engine
from turboweb.paths import safe_segment


@pytest.mark.skipif(not os.environ.get('TURBOWEB_TEST_BROWSER'), reason='Set TURBOWEB_TEST_BROWSER')
def test_nested_website_and_cdn_paths_work_offline(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    cdn = Flask('cdn')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><rect width="12" height="12" fill="red"/></svg>'

    @cdn.get('/brand/logo.svg')
    def logo():
        return Response(svg, mimetype='image/svg+xml')

    cdn_server = make_server('127.0.0.1',0,cdn,threaded=True)
    threading.Thread(target=cdn_server.serve_forever,daemon=True).start()
    cdn_url = f'http://127.0.0.1:{cdn_server.server_port}'
    site = Flask('nested')

    def html(title, link):
        return f'<html><head><link rel="stylesheet" href="/assets/css/style.css"></head><body><h1>{title}</h1><a href="{link}">Navigate</a><img id="logo" src="{cdn_url}/brand/logo.svg"><img src="{cdn_url}/brand/logo.svg?v=2"></body></html>'

    @site.get('/')
    def home():
        return html('Home','/docs/chapter/')

    @site.get('/docs/chapter/')
    def chapter():
        return html('Chapter','/')

    @site.get('/assets/css/style.css')
    def css():
        return Response('@import "theme.css"; body{background-image:url("../../images/photo.svg")}',mimetype='text/css')

    @site.get('/assets/css/theme.css')
    def theme():
        return Response('h1{color:rgb(17, 34, 51)}',mimetype='text/css')

    @site.get('/images/photo.svg')
    def photo():
        return Response(svg,mimetype='image/svg+xml')

    server = make_server('127.0.0.1',0,site,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    start = f'http://127.0.0.1:{server.server_port}/'
    monkeypatch.setenv('TURBOWEB_CHROMIUM',os.environ['TURBOWEB_TEST_BROWSER'])
    monkeypatch.setattr(engine,'public_url',lambda url:url)
    manager = engine.ArchiveManager(tmp_path)
    job = dict(id='nested',name='Nested',url=start,options={**engine.DEFAULTS,'delay':0,'depth':1,'max_pages':2,'respect_robots':False,'use_sitemap':False},status='queued',created=0,pages=0,assets=0,bytes=0,failed=0,logs=[],message='',entry=None)
    manager.jobs['nested'] = job
    manager.cancel_events['nested'] = threading.Event()
    try:
        manager.run(job)
        assert job['status'] == 'completed', job['logs']
        folder = tmp_path/'nested'
        host = safe_segment(urlsplit(start).netloc)
        cdn_host = safe_segment(urlsplit(cdn_url).netloc)
        for name in ('index.html','assets/css/style.css','assets/css/theme.css','images/photo.svg','docs/chapter/index.html'):
            assert (folder/'files'/host/name).is_file(), name
        assert (folder/'files'/cdn_host/'brand/logo.svg').is_file()
        manifest = json.loads((folder/'manifest.json').read_text())
        assert manifest['urls'][cdn_url+'/brand/logo.svg?v=2'] != manifest['urls'][cdn_url+'/brand/logo.svg']
        assert job['bytes'] > 0
        from turboweb.exports import build_export
        with zipfile.ZipFile(build_export(tmp_path,job)) as archive:
            assert f'files/{host}/assets/css/style.css' in archive.namelist()
            assert f'files/{host}/docs/chapter/index.html' in archive.namelist()
            assert f'files/{cdn_host}/brand/logo.svg' in archive.namelist()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['TURBOWEB_TEST_BROWSER'],headless=True)
            page = browser.new_page()
            page.route('http://**/*',lambda route:route.abort())
            page.route('https://**/*',lambda route:route.abort())
            page.goto((folder/'index.html').as_uri())
            assert page.locator('h1').inner_text() == 'Home'
            page.wait_for_function("document.querySelector('#logo').complete && document.querySelector('#logo').naturalWidth === 12")
            page.get_by_role('link',name='Navigate').click()
            assert page.locator('h1').inner_text() == 'Chapter'
            page.wait_for_function("getComputedStyle(document.querySelector('h1')).color === 'rgb(17, 34, 51)'")
            page.wait_for_function("document.querySelector('#logo').complete && document.querySelector('#logo').naturalWidth === 12")
            browser.close()
    finally:
        server.shutdown()
        cdn_server.shutdown()
