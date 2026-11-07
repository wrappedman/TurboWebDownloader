"""Opt-in English UI smoke check with a temporary, empty workspace."""
import os
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
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.wait_for_selector('#wizard[open]')
            page.locator('#project-name').fill('Design library')
            page.locator('#project-url').fill('https://example.com')
            page.locator('#wizard-next').click()
            assert page.locator('[data-step="1"]').is_visible()
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
