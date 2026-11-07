import json
import socket
import threading

import pytest
from bs4 import BeautifulSoup

from turboweb.engine import (DEFAULTS, ArchiveManager, file_name, local_ref,
                             normalize_url, public_url, rewrite_css, rewrite_html)


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:secret@example.com', 'http://', ''])
def test_reject_invalid_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_normalization_and_names():
    assert normalize_url(' https://example.com#hello ') == 'https://example.com/'
    assert file_name('https://example.com/a?q=1', page=True).endswith('.html')
    assert file_name('https://example.com/a?q=1', page=True) != file_name('https://example.com/a?q=2', page=True)
    assert '/' not in file_name('https://example.com/../../evil', 'text/css')


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '192.168.1.1'])
def test_private_network_guard(monkeypatch, ip):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a: [(0,0,0,'',(ip,80))])
    with pytest.raises(ValueError):
        public_url('http://example.com')


def test_relative_links_fragments_css_and_script_policy():
    base = 'https://example.com/docs/'
    mapping = {'https://example.com/docs/next': 'page.html', 'https://example.com/image.png': 'image.png',
               'https://example.com/docs/style.css': 'style.css', 'https://example.com/docs/x.js': 'x.js'}
    html = '''<html><head><base href="/docs/"><meta http-equiv="Content-Security-Policy" content="default-src none"><link href="style.css" integrity="abc"></head><body onload="bad()"><a href="next#intro">Next</a><img src="/image.png" srcset="/image.png 1x, /image.png 2x"><div style="background:url('/image.png')"></div><script src="x.js"></script></body></html>'''
    soup = BeautifulSoup(rewrite_html(html, base, mapping, DEFAULTS), 'html.parser')
    assert soup.a['href'] == 'page.html#intro'
    assert soup.img['src'] == 'image.png'
    assert soup.img['srcset'] == 'image.png 1x, image.png 2x'
    assert soup.link['href'] == 'style.css'
    assert not soup.find('base') and not soup.find('script') and not soup.find('meta')
    assert 'onload' not in soup.body.attrs and 'integrity' not in soup.link.attrs
    assert 'url("image.png")' in soup.div['style']
    assert 'src="x.js"' in rewrite_html(html, base, mapping, {**DEFAULTS, 'run_scripts': True})
    assert local_ref('outside', base, {}) == base+'outside'
    assert local_ref('#x', base, {}) == '#x'
    assert local_ref('data:image/png;base64,abcd', base, {}) == 'data:image/png;base64,abcd'


def test_css_rewriting():
    result = rewrite_css('@import "theme.css";a{background:url(../x.png)}', 'https://example.com/css/a.css', {'https://example.com/css/theme.css':'theme.css','https://example.com/x.png':'image.png'})
    assert '@import "theme.css"' in result
    assert 'url("image.png")' in result


def test_restart_recovers_interrupted_project(tmp_path):
    folder = tmp_path/'abc'
    folder.mkdir()
    (folder/'project.json').write_text(json.dumps(dict(id='abc',status='running')))
    manager = ArchiveManager(tmp_path)
    assert manager.jobs['abc']['status'] == 'interrupted'
    assert json.loads((folder/'project.json').read_text())['status'] == 'interrupted'


def test_cancel_queued_job(tmp_path):
    manager = ArchiveManager(tmp_path)
    job = dict(id='abc', status='queued', logs=[])
    manager.jobs['abc'] = job
    event = threading.Event()
    event.set()
    manager.cancel_events['abc'] = event
    manager.run(job)
    assert job['status'] == 'cancelled'
