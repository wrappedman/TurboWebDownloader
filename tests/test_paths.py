from pathlib import PurePosixPath

from turboweb.engine import DEFAULTS, rewrite_html, rewrite_css
from turboweb.paths import WebsiteLayout, website_path, relative_url


def test_original_names_and_folders():
    assert website_path('https://example.com/assets/css/style.css','text/css') == 'example.com/assets/css/style.css'
    assert website_path('https://example.com/images/logo.jpg','image/jpeg') == 'example.com/images/logo.jpg'
    assert website_path('https://example.com/docs/guide.html',page=True) == 'example.com/docs/guide.html'
    assert website_path('https://example.com/docs/',page=True) == 'example.com/docs/index.html'
    assert website_path('https://example.com/docs',page=True) == 'example.com/docs/index.html'
    assert website_path('https://example.com/view.php',page=True) == 'example.com/view.php.html'
    assert website_path('https://cdn.example.com/fonts/font.woff2','font/woff2') == 'cdn.example.com/fonts/font.woff2'


def test_queries_and_case_collisions_do_not_overwrite():
    layout = WebsiteLayout()
    a = layout.allocate('https://example.com/img/logo.png?v=1','image/png')
    b = layout.allocate('https://example.com/img/logo.png?v=2','image/png')
    assert a != b and a.startswith('example.com/img/logo__q_')
    assert layout.allocate('https://example.com/img/logo.png?v=1','image/png') == a
    upper = layout.allocate('https://example.com/LOGO.png','image/png')
    lower = layout.allocate('https://example.com/logo.png','image/png')
    assert upper.casefold() != lower.casefold()
    root = layout.allocate('https://example.com/docs',page=True)
    slash = layout.allocate('https://example.com/docs/',page=True)
    assert root != slash


def test_file_directory_conflicts_both_orders():
    for reverse in (False, True):
        layout = WebsiteLayout()
        urls = ['https://example.com/file.css','https://example.com/file.css/nested.css']
        if reverse:
            urls.reverse()
        paths = [PurePosixPath(layout.allocate(url,'text/css')) for url in urls]
        assert paths[0] not in paths[1].parents and paths[1] not in paths[0].parents


def test_windows_unsafe_names_traversal_and_path_length():
    for url in ['https://example.com/../../secret.css', 'https://example.com/%2e%2e/%2f..%5cevil.css',
                'https://example.com/CON/logo?.png', 'https://example.com/a:b/*logo.png',
                'https://example.com/' + '/'.join(['long'*40]*10) + '/image.png']:
        path = website_path(url, 'image/png')
        assert not PurePosixPath(path).is_absolute()
        assert '..' not in PurePosixPath(path).parts
        assert all(not any(c in part for c in '<>:"\\|?*') for part in PurePosixPath(path).parts)
        assert len(path) <= 180
    assert '/_CON/' in website_path('https://example.com/CON/logo.png','image/png')


def test_nested_relative_links_and_url_encoding():
    mapping = {'https://example.com/assets/style.css':'example.com/assets/style.css',
               'https://cdn.example.com/my logo.svg':'cdn.example.com/my logo.svg',
               'https://example.com/docs/next':'example.com/docs/next/index.html'}
    source = 'example.com/docs/start/index.html'
    html = '<link rel="stylesheet" href="/assets/style.css"><img src="https://cdn.example.com/my logo.svg"><a href="../next#part">Next</a>'
    result = rewrite_html(html,'https://example.com/docs/start/',mapping,DEFAULTS,source)
    assert '../../assets/style.css' in result
    assert '../../../cdn.example.com/my%20logo.svg' in result
    assert '../next/index.html#part' in result
    css = rewrite_css('a{background:url("https://cdn.example.com/my logo.svg")}', 'https://example.com/assets/style.css',mapping,'example.com/assets/style.css')
    assert '../../cdn.example.com/my%20logo.svg' in css
    assert relative_url('example.com/a%2Fb.png','example.com/index.html') == 'a%252Fb.png'
