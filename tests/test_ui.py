"""Opt-in English UI smoke check with a temporary, empty workspace."""
import os
import zipfile
import threading

import pytest
from werkzeug.serving import make_server

from turboweb.app import create_app


@pytest.mark.skipif(not os.environ.get('TURBOWEB_TEST_BROWSER'), reason='Set TURBOWEB_TEST_BROWSER to opt into UI tests')
def test_wizard_preferences_about_and_mobile(tmp_path):
    from playwright.sync_api import sync_playwright
    server = make_server('127.0.0.1', 0, create_app(tmp_path), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['TURBOWEB_TEST_BROWSER'], headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/scans', lambda route: route.fulfill(status=202, json=dict(id='fixture-scan',status='completed',discovered=37,sitemap_count=30,inspected=10,warnings=[],message='Discovery finished.')) )
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.wait_for_selector('#wizard[open]')
            page.locator('#project-name').fill('Design library')
            page.locator('#project-url').fill('https://example.com')
            page.locator('#wizard-next').click()
            assert page.locator('[data-step="1"]').is_visible()
            page.locator('#scan-use').wait_for(state='visible')
            assert '37 known page URLs' in page.locator('#scan-summary').inner_text()
            page.locator('#scan-use').click()
            assert page.locator('#project-form [name="max_pages"]').input_value() == '37'
            page.locator('[name="depth"]').fill('1')
            page.locator('#wizard-next').click()
            assert 'Design library' in page.locator('#review').inner_text()
            page.locator('#wizard-next').click()
            assert 'permission' in page.locator('#form-error').inner_text()
            page.locator('#wizard [data-close]').click()
            page.locator('#about').click()
            assert 'behnam ehsani' in page.locator('#information').inner_text()
            assert page.get_by_role('link', name='inbox.ehsani@gmail.com').is_visible()
            page.locator('#information [data-close]').click()
            page.locator('#preferences').click()
            page.locator('#preferences-form [name="max_pages"]').fill('12')
            page.get_by_role('button', name='Save preferences').click()
            page.locator('#new-project').click()
            page.locator('#project-name').fill('Test')
            page.locator('#project-url').fill('https://example.com')
            page.locator('#wizard-next').click()
            assert page.locator('#project-form [name="max_pages"]').input_value() == '12'
            page.locator('#wizard [data-close]').click()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown()


@pytest.mark.skipif(not os.environ.get('TURBOWEB_TEST_BROWSER'), reason='Set TURBOWEB_TEST_BROWSER to opt into UI tests')
def test_zip_download_and_native_export_dispatch(tmp_path):
    from playwright.sync_api import sync_playwright
    app = create_app(tmp_path)
    manager = app.extensions['archives']
    manager.jobs['abc'] = dict(id='abc',name='Export fixture',url='https://example.com/',
        created=0,status='completed',pages=1,assets=0,bytes=20,failed=0,logs=[],
        message='Ready',entry='start.html')
    folder = tmp_path/'abc'
    (folder/'files').mkdir(parents=True)
    (folder/'files'/'start.html').write_text('<h1>Offline</h1>')
    (folder/'index.html').write_text('Archive entry')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['TURBOWEB_TEST_BROWSER'], headless=True)
            page = browser.new_page(accept_downloads=True)
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.get_by_role('button', name='Open project').click()
            assert str(folder) in page.locator('.project-location').inner_text()
            with page.expect_download() as event:
                page.get_by_role('button', name='Save as ZIP').click()
            download = event.value
            assert download.failure() is None
            assert download.suggested_filename.endswith('.zip')
            with zipfile.ZipFile(download.path()) as archive:
                assert archive.read('files/start.html') == b'<h1>Offline</h1>'
            page.evaluate("window.pywebview = {api: {export_project: async (id) => ({path: 'C:/Exports/' + id + '.zip'})}}")
            page.get_by_role('button', name='Save as ZIP').click()
            page.wait_for_function("document.querySelector('#toast').textContent.includes('C:/Exports/abc.zip')")
            page.get_by_role('button', name='Delete project', exact=True).click()
            assert page.locator('#delete-dialog [value="keep"]').is_checked()
            page.locator('#delete-cancel').click()
            assert 'abc' in manager.jobs and folder.exists()
            page.get_by_role('button', name='Delete project', exact=True).click()
            page.get_by_role('button', name='Remove from library', exact=True).click()
            page.wait_for_function("!document.querySelector('#delete-dialog').open")
            assert 'abc' not in manager.jobs and folder.exists()
            with manager.lock:
                manager.jobs['purge'] = {**manager.jobs.get('abc', {}), 'id':'purge','name':'Purge fixture',
                    'url':'https://example.com/','created':1,'status':'completed','pages':1,'assets':0,
                    'bytes':20,'failed':0,'logs':[],'message':'Ready','entry':'start.html'}
                manager.save(manager.jobs['purge'])
            purge = tmp_path/'purge'
            (purge/'files').mkdir()
            (purge/'files/start.html').write_text('Offline')
            page.reload()
            page.locator('button[data-detail="purge"]').click()
            page.get_by_role('button',name='Delete project',exact=True).click()
            page.locator('#delete-dialog [value="files"]').check()
            page.get_by_role('button',name='Delete project & files',exact=True).click()
            page.wait_for_function("!document.querySelector('#delete-dialog').open")
            assert 'purge' not in manager.jobs and not purge.exists()
            browser.close()
    finally:
        server.shutdown()
