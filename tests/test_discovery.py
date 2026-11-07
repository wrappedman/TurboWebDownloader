import gzip

from turboweb import discovery
from turboweb.capture_tools import css_dependencies


def test_nested_sitemaps_ignore_image_locations(monkeypatch):
    docs = {
        'https://site.test/sitemap.xml': b'<sitemapindex><sitemap><loc>/pages.xml</loc></sitemap></sitemapindex>',
        'https://site.test/pages.xml': b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>/a</loc><image:image><image:loc>https://site.test/photo.png</image:loc></image:image></url><url><loc>/a#anchor</loc></url><url><loc>https://other.test/foreign</loc></url></urlset>',
    }
    monkeypatch.setattr(discovery, 'fetch_resource', lambda ctx,url,validate,**kwargs: (url,'application/xml',docs[url]))
    urls, warnings, bounded = discovery.sitemap_urls(None,'https://site.test/',lambda _:None)
    assert urls == ['https://site.test/a']
    assert not warnings and not bounded


def test_gzip_sitemap_and_unavailable_file(monkeypatch):
    xml = gzip.compress(b'<urlset><url><loc>/a</loc></url></urlset>')
    monkeypatch.setattr(discovery, 'fetch_resource', lambda ctx,url,validate,**kwargs: (url,'application/gzip',xml))
    assert discovery.sitemap_urls(None,'https://site.test/',lambda _:None)[0] == ['https://site.test/a']
    def unavailable(*args, **kwargs):
        raise ValueError('HTTP 404')
    monkeypatch.setattr(discovery, 'fetch_resource', unavailable)
    urls, warnings, bounded = discovery.sitemap_urls(None,'https://site.test/',lambda _:None)
    assert not urls and '404' in warnings[0]


def test_extensionless_css_import_and_font_dependencies():
    deps = dict(css_dependencies('@import url("/theme?id=1"); @font-face{src:url("/font?id=2")} a{background:url(/photo)}'))
    assert deps == {'/theme?id=1':'styles','/font?id=2':'fonts','/photo':'images'}
