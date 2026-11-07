from pathlib import Path
from types import SimpleNamespace

import pytest

from turboweb import browser


class FakeChromium:
    def __init__(self, path, fail=False):
        self.executable_path = str(path)
        self.calls = []
        self.fail = fail

    def launch(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError('Browser launch failed')
        return 'browser instance'


def test_installed_edge_when_download_missing(tmp_path, monkeypatch):
    monkeypatch.delenv('TURBOWEB_CHROMIUM', raising=False)
    edge = tmp_path / 'Microsoft/Edge/Application/msedge.exe'
    edge.parent.mkdir(parents=True)
    edge.touch()
    monkeypatch.setattr(browser.sys, 'platform', 'win32')
    monkeypatch.setenv('PROGRAMFILES', str(tmp_path))
    monkeypatch.delenv('PROGRAMFILES(X86)', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setattr(browser.shutil, 'which', lambda _: None)
    chromium = FakeChromium(tmp_path / 'missing-chromium')
    instance, label = browser.launch_browser(SimpleNamespace(chromium=chromium))
    assert instance == 'browser instance'
    assert label == 'Microsoft Edge'
    assert chromium.calls[0]['executable_path'] == str(edge)
    assert chromium.calls[0]['headless'] is True


def test_bundled_browser_preferred(tmp_path, monkeypatch):
    monkeypatch.delenv('TURBOWEB_CHROMIUM', raising=False)
    bundled = tmp_path / 'chromium'
    bundled.touch()
    monkeypatch.setattr(browser, 'installed_browsers', lambda: [('Edge', 'edge')])
    chromium = FakeChromium(bundled)
    assert browser.launch_browser(SimpleNamespace(chromium=chromium))[1] == 'Playwright Chromium'
    assert len(chromium.calls) == 1


def test_explicit_override(tmp_path, monkeypatch):
    custom = tmp_path / 'my chrome.exe'
    custom.touch()
    monkeypatch.setenv('TURBOWEB_CHROMIUM', '"' + str(custom) + '"')
    chromium = FakeChromium(tmp_path / 'missing')
    assert browser.launch_browser(SimpleNamespace(chromium=chromium))[1] == 'Custom Chromium'
    assert chromium.calls[0]['executable_path'] == str(custom)


def test_bad_override_reports_path(tmp_path, monkeypatch):
    monkeypatch.setenv('TURBOWEB_CHROMIUM', str(tmp_path / 'missing'))
    with pytest.raises(RuntimeError, match='TURBOWEB_CHROMIUM'):
        browser.browser_candidates(SimpleNamespace(chromium=FakeChromium('missing')))


def test_no_browser_has_actionable_message(monkeypatch):
    monkeypatch.delenv('TURBOWEB_CHROMIUM', raising=False)
    monkeypatch.setattr(browser, 'installed_browsers', lambda: [])
    with pytest.raises(RuntimeError, match='Install Google Chrome or Microsoft Edge'):
        browser.launch_browser(SimpleNamespace(chromium=FakeChromium('missing')))


def test_launch_failure_tries_next_browser(tmp_path, monkeypatch):
    monkeypatch.delenv('TURBOWEB_CHROMIUM', raising=False)
    bundled = tmp_path / 'chromium'
    bundled.touch()
    monkeypatch.setattr(browser, 'installed_browsers', lambda: [('Edge', 'edge')])
    chromium = FakeChromium(bundled)
    def launch(**kwargs):
        if kwargs['executable_path'] == str(bundled):
            raise RuntimeError('First browser failed')
        return 'fallback instance'
    chromium.launch = launch
    assert browser.launch_browser(SimpleNamespace(chromium=chromium)) == ('fallback instance', 'Edge')
