import builtins
import json
import os
import sys
from types import SimpleNamespace

import pytest

import desktop


def test_frozen_browser_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', 'old')
    desktop.prepare_environment()
    assert os.environ['PLAYWRIGHT_BROWSERS_PATH'] == str(tmp_path/'browsers')


def test_self_test_reports_dependency_failure(monkeypatch, tmp_path):
    original = builtins.__import__
    def without_webview(name, *args, **kwargs):
        if name == 'webview':
            raise ImportError('simulated missing desktop dependency')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_webview)
    path = tmp_path/'logs'/'report.json'
    assert desktop.packaged_self_test(path) == 1
    result = json.loads(path.read_text())
    assert result['ok'] is False
    assert 'simulated missing desktop dependency' in result['error']


@pytest.mark.skipif(not os.environ.get('TURBOWEB_TEST_BROWSER'), reason='Set TURBOWEB_TEST_BROWSER')
def test_self_test_non_gui_flow(monkeypatch, tmp_path):
    # Actual packaged pywebview/clr imports are verified by the Windows build.
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace())
    monkeypatch.setenv('TURBOWEB_CHROMIUM', os.environ['TURBOWEB_TEST_BROWSER'])
    report = tmp_path/'self-test.json'
    assert desktop.packaged_self_test(report) == 0
    assert json.loads(report.read_text())['ok'] is True
