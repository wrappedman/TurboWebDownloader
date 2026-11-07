from types import SimpleNamespace

import pytest

from turboweb.capture_tools import fetch_resource, html_resources, srcset_items


class Response:
    def __init__(self, status=200, headers=None, body=b'ok'):
        self.status = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
        self.data = body
        self.disposed = False

    def body(self):
        return self.data

    def dispose(self):
        self.disposed = True


def context_for(responses):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)
    return SimpleNamespace(request=SimpleNamespace(get=get)), calls


def test_redirects_are_checked_and_responses_disposed():
    redirect = Response(302, {'location':'/image.svg'})
    image = Response(200, {'content-type':'image/svg+xml'}, b'<svg/>')
    context, calls = context_for([redirect, image])
    checked = []
    result = fetch_resource(context, 'https://site.test/redirect', checked.append)
    assert checked == ['https://site.test/redirect','https://site.test/image.svg']
    assert result == ('https://site.test/image.svg','image/svg+xml',b'<svg/>')
    assert redirect.disposed and image.disposed
    assert all(call[1]['max_redirects'] == 0 for call in calls)


def test_retry_transient_failure(monkeypatch):
    monkeypatch.setattr('turboweb.capture_tools.time.sleep', lambda _: None)
    first = Response(503)
    context, calls = context_for([first, Response()])
    assert fetch_resource(context, 'https://site.test/x', lambda _: None)[2] == b'ok'
    assert len(calls) == 2 and first.disposed


def test_404_not_retried_and_size_limit():
    context, calls = context_for([Response(404)])
    with pytest.raises(ValueError, match='404'):
        fetch_resource(context, 'https://site.test/x', lambda _: None)
    assert len(calls) == 1
    context, _ = context_for([Response(body=b'too much')])
    with pytest.raises(ValueError, match='size limit'):
        fetch_resource(context, 'https://site.test/x', lambda _: None, limit=2)


def test_dom_resource_discovery_and_srcset():
    html = '<picture><source srcset="a.webp 1x, b.webp 2x"><img data-src="lazy.jpg"></picture><svg><image xlink:href="icon.svg"/></svg><div style="background:url(bg.png)"></div><link rel="stylesheet" href="theme.css">'
    refs = set(html_resources(html, 'https://site.test/docs/'))
    assert {('https://site.test/docs/'+name, category) for name,category in [('a.webp','images'),('b.webp','images'),('lazy.jpg','images'),('icon.svg','images'),('bg.png','images'),('theme.css','styles')]} <= refs
    assert list(srcset_items('data:image/png;base64,AAAA 1x, two.png 2x')) == [('data:image/png;base64,AAAA','1x'),('two.png','2x')]
