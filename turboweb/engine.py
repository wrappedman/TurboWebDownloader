"""Bounded browser-based archiver. No target server source is retrieved."""
import hashlib
import ipaddress
import json
import mimetypes
import re
import socket
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

from .browser import launch_browser
from .capture_tools import (prepare_page, html_resources,
                            fetch_resource, srcset_items, css_dependencies, snapshot_html, RESOURCE_LIMIT, TOTAL_LIMIT)

ASSET_TYPES = {'stylesheet': 'styles', 'script': 'scripts', 'image': 'images', 'font': 'fonts', 'media': 'media'}
DEFAULTS = dict(max_pages=25, depth=2, delay=500, timeout=30000, images=True,
                styles=True, scripts=True, fonts=True, media=False, beautify=True,
                run_scripts=False, respect_robots=True, use_sitemap=True)


def normalize_url(url):
    url = urldefrag(url.strip())[0]
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Enter a public HTTP or HTTPS website URL without credentials.')
    return parts._replace(path=parts.path or '/', fragment='').geturl()


def public_url(url):
    """Block private network requests, including subresources and redirects."""
    parts = urlsplit(normalize_url(url))
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private, local and reserved network addresses are not supported.')
    return url


def file_name(url, content_type='', page=False):
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    ext = '.html' if page else mimetypes.guess_extension(content_type.split(';')[0].strip())
    if ext == '.jpe':
        ext = '.jpg'
    if not ext:
        suffix = Path(urlsplit(url).path).suffix
        ext = suffix if re.fullmatch(r'\.[a-zA-Z0-9]{1,8}', suffix) else '.bin'
    return digest + ext


def local_ref(value, base, mapping):
    if not value or value.startswith(('data:', 'blob:', '#', 'mailto:', 'tel:', 'javascript:')):
        return value
    absolute, fragment = urldefrag(urljoin(base, value))
    return mapping.get(absolute, absolute) + ('#' + fragment if fragment else '')


def rewrite_css(text, base, mapping):
    def replace(match):
        return 'url("' + local_ref(match.group(2).strip(), base, mapping).replace('"', '%22') + '")'
    text = re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', replace, text, flags=re.I)
    return re.sub(r'(@import\s+)([\'"])(.*?)\2', lambda m: m[1] + '"' + local_ref(m[3], base, mapping) + '"', text, flags=re.I)


def rewrite_html(html, base, mapping, options):
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup.find_all('base'):
        el.decompose()
    for el in soup.select('meta[http-equiv]'):
        if el.get('http-equiv', '').lower() in ('content-security-policy', 'refresh'):
            el.decompose()
    for el in soup.find_all(True):
        for attr in ('href', 'src', 'poster', 'action', 'data-src', 'data-original', 'data-lazy-src', 'xlink:href'):
            if el.has_attr(attr):
                el[attr] = local_ref(el[attr], base, mapping)
        for attr in ('integrity', 'crossorigin', 'nonce'):
            el.attrs.pop(attr, None)
        for attr in ('srcset', 'data-srcset'):
            if el.has_attr(attr):
                el[attr] = ', '.join(local_ref(url, base, mapping) + (' ' + desc if desc else '') for url, desc in srcset_items(el[attr]))
        if el.has_attr('style'):
            el['style'] = rewrite_css(el['style'], base, mapping)
        if not options['run_scripts']:
            for attr in list(el.attrs):
                if attr.lower().startswith('on'):
                    del el[attr]
    for style in soup.find_all('style'):
        style.string = rewrite_css(style.get_text(), base, mapping)
    if not options['run_scripts']:
        for script in soup.find_all('script'):
            script.decompose()
    return soup.prettify() if options['beautify'] else str(soup)


class ArchiveManager:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.cancel_events = {}
        for path in self.root.glob('*/project.json'):
            try:
                data = json.loads(path.read_text('utf-8'))
                if data['status'] in ('queued', 'running', 'stopping'):
                    data.update(status='interrupted', message='Interrupted. You can retry this project.')
                self.jobs[data['id']] = data
                self.save(data)
            except (ValueError, KeyError, OSError):
                pass
        self.gate = threading.Semaphore(1)

    def save(self, job):
        folder = self.root / job['id']
        folder.mkdir(exist_ok=True)
        path = folder / 'project.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(job, indent=2), encoding='utf-8')
        temporary.replace(path)

    def update(self, job, **changes):
        with self.lock:
            job.update(changes)
            self.save(job)

    def log(self, job, text, level='info'):
        with self.lock:
            job['logs'].append(dict(time=time.strftime('%H:%M:%S'), message=text, level=level))
            job['logs'] = job['logs'][-250:]
            self.save(job)

    def create(self, name, url, options):
        import uuid
        ident = uuid.uuid4().hex[:12]
        job = dict(id=ident, name=name, url=url, options=options, status='queued',
                   created=time.time(), pages=0, assets=0, bytes=0, failed=0, logs=[],
                   message='Waiting for browser…', entry=None, failed_assets=0, discovered=1)
        with self.lock:
            self.jobs[ident] = job
            self.cancel_events[ident] = threading.Event()
            self.save(job)
        threading.Thread(target=self.run, args=(job,), daemon=True).start()
        return job

    def run(self, job):
        event = self.cancel_events[job['id']]
        with self.gate:
            if event.is_set():
                self.update(job, status='cancelled', message='Cancelled before capture.')
                return
            self.update(job, status='running', message='Launching Chromium…')
            try:
                self.capture(job, event)
                status = 'cancelled' if event.is_set() else ('completed' if job['pages'] else 'failed')
                self.update(job, status=status, message='Capture stopped; partial archive retained.' if event.is_set() else (f"Archive ready: {job['pages']} pages saved, {job['failed']} page failures and {job.get('failed_assets', 0)} resource failures." if job['pages'] else 'No pages could be captured. See the activity log.'))
            except Exception as exc:
                self.log(job, str(exc), 'error')
                self.update(job, status='failed', message='Capture failed. See the activity log for details.')
            finally:
                folder = self.root / job['id']
                (folder / 'report.json').write_text(json.dumps(job, indent=2), encoding='utf-8')

    def capture(self, job, event):
        from playwright.sync_api import sync_playwright
        from urllib.robotparser import RobotFileParser
        options = {**DEFAULTS, **job['options']}
        folder = self.root / job['id'] / 'files'
        folder.mkdir(exist_ok=True)
        mapping, assets, pages = {}, {}, []
        queue = deque([(job['url'], 0)])
        seen = set()
        origin = urlsplit(job['url']).netloc
        robots = None
        robots_text = ''
        with sync_playwright() as p:
            browser, browser_label = launch_browser(p)
            self.log(job, 'Capture browser: ' + browser_label)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1, accept_downloads=False, service_workers='block', user_agent='TurboWebDownloader/1.0 (personal offline archive)')
            def route_request(route):
                try:
                    if event.is_set():
                        route.abort()
                        return
                    public_url(route.request.url)
                    category = ASSET_TYPES.get(route.request.resource_type)
                    # Scripts still execute during rendering even when the user
                    # chooses not to store JavaScript in the resulting archive.
                    if category and category != 'scripts' and not options[category]:
                        route.abort()
                    else:
                        route.continue_()
                except Exception:
                    route.abort()
            context.route('**/*', route_request)
            page = context.new_page()
            page.set_default_timeout(options['timeout'])
            if options['respect_robots']:
                robots_url = urljoin(job['url'], '/robots.txt')
                self.log(job, 'Checking robots.txt…')
                try:
                    response = page.goto(robots_url, wait_until='domcontentloaded')
                    if response and response.ok:
                        robots = RobotFileParser()
                        robots_text = response.text()
                        robots.parse(robots_text.splitlines())
                    elif response and response.status in (401, 403):
                        raise ValueError('robots.txt access denied; capture stopped to respect site policy.')
                except ValueError:
                    raise
                except Exception as exc:
                    self.log(job, 'Could not read robots.txt: ' + str(exc)[:160], 'warning')

            if options['use_sitemap'] and options['depth'] > 0:
                from .discovery import sitemap_urls
                links, warnings, bounded = sitemap_urls(context, job['url'], public_url, robots_text, event)
                for link in links:
                    if link != job['url']:
                        queue.append((link, 1))
                self.update(job, discovered=len(set(links) | {job['url']}))
                self.log(job, f'Sitemap discovery: {len(links)} URLs' + (' (bounded)' if bounded else ''))
                for warning in warnings[:5]:
                    self.log(job, warning, 'warning')
            scheduled = {url for url, _ in queue}
            discovered = set(scheduled)
            total = [0]
            missing = {}
            def store_asset(url, mime, body, aliases=()):
                if url in assets:
                    for alias in aliases:
                        mapping[alias] = mapping[url]
                    return
                if len(body) > RESOURCE_LIMIT or total[0] + len(body) > TOTAL_LIMIT:
                    raise ValueError('Resource size budget exceeded')
                if 'text/html' in mime:
                    raise ValueError('Expected a resource, received an HTML page')
                filename = file_name(url, mime)
                (folder / filename).write_bytes(body)
                assets[url] = (filename, mime)
                mapping[url] = filename
                for alias in aliases:
                    mapping[alias] = filename
                missing.pop(url, None)
                total[0] += len(body)
                self.update(job, assets=len(assets), bytes=total[0])

            def response_received(response):
                category = ASSET_TYPES.get(response.request.resource_type)
                if event.is_set() or not category or not options[category]:
                    return
                url = urldefrag(response.url)[0]
                if url in assets:
                    return
                missing[url] = category
                if not response.ok:
                    return
                try:
                    if int(response.headers.get('content-length', 0)) > RESOURCE_LIMIT:
                        raise ValueError('Resource exceeds 25 MB')
                    aliases = []
                    request = response.request.redirected_from
                    while request:
                        aliases.append(urldefrag(request.url)[0])
                        request = request.redirected_from
                    store_asset(url, response.headers.get('content-type', ''), response.body(), aliases)
                except Exception as exc:
                    self.log(job, 'Resource queued for recovery: ' + url + ' — ' + str(exc)[:100], 'warning')
            page.on('response', response_received)
            try:
                while queue and len(pages) < options['max_pages'] and not event.is_set():
                    url, depth = queue.popleft()
                    if url in seen:
                        continue
                    seen.add(url)
                    if robots and not robots.can_fetch('TurboWebDownloader', url):
                        self.log(job, 'robots.txt disallows: ' + url, 'warning')
                        continue
                    self.update(job, message='Rendering ' + url)
                    self.log(job, 'Rendering ' + url)
                    try:
                        response = None
                        for attempt in range(3):
                            try:
                                response = page.goto(url, wait_until='domcontentloaded')
                                if response and response.status >= 400:
                                    if response.status != 429 and response.status < 500:
                                        raise ValueError('HTTP ' + str(response.status))
                                    raise OSError('HTTP ' + str(response.status))
                                break
                            except ValueError:
                                raise
                            except Exception:
                                if attempt == 2 or event.is_set():
                                    raise
                                page.wait_for_timeout(500 * (attempt + 1))
                        if response and 'text/html' not in response.headers.get('content-type', 'text/html'):
                            self.log(job, 'Skipped non-HTML page: ' + url, 'warning')
                            continue
                        try:
                            page.wait_for_load_state('networkidle', timeout=min(5000, options['timeout']))
                        except Exception:
                            pass
                        reached_bottom = prepare_page(page, event)
                        if not reached_bottom:
                            self.log(job, 'Scroll budget reached; infinite or very long content may be partial.', 'warning')
                        page.wait_for_timeout(options['delay'])
                        final_url = normalize_url(page.url)
                        if not pages and url == job['url']:
                            origin = urlsplit(final_url).netloc
                        if urlsplit(final_url).netloc != origin:
                            self.log(job, 'Skipped page redirected outside the target site.', 'warning')
                            continue
                        base = page.evaluate('document.baseURI')
                        html = snapshot_html(page)
                        filename = file_name(url, page=True)
                        mapping[url] = filename
                        mapping[final_url] = filename
                        pages.append((url, base, filename, html))
                        if not job['entry']:
                            self.update(job, entry=filename)
                            try:
                                page.screenshot(path=str(folder.parent / 'preview.png'), animations='disabled', timeout=5000)
                            except Exception:
                                pass
                        self.update(job, pages=len(pages))
                        if depth < options['depth']:
                            for href in page.locator('a[href]').evaluate_all('(nodes) => nodes.map(n => n.href)'):
                                try:
                                    link = normalize_url(href)
                                    if urlsplit(link).netloc == origin:
                                        if len(discovered) < 10000:
                                            discovered.add(link)
                                        if link not in scheduled and len(queue) < 10000:
                                            scheduled.add(link)
                                            queue.append((link, depth + 1))
                                except ValueError:
                                    pass
                            self.update(job, discovered=len(discovered))
                    except Exception as exc:
                        self.update(job, failed=job['failed'] + 1)
                        self.log(job, 'Page failed: ' + url + ' — ' + str(exc)[:220], 'error')
                # Recover resources never requested by the browser (responsive variants,
                # lazy attributes, CSS imports/fonts/backgrounds), plus failed responses.
                self.update(job, message='Recovering images and dependent resources…')
                pending = deque((url, category, job['url']) for url, category in missing.items())
                for _, base, _, html in pages:
                    pending.extend((url, category, base) for url, category in html_resources(html, base))
                expanded_css = set()
                attempted = set()
                failures = []
                while (pending or any('css' in mime and url not in expanded_css for url, (_, mime) in assets.items())) and not event.is_set():
                    for url, (filename, mime) in list(assets.items()):
                        if 'css' in mime and url not in expanded_css:
                            expanded_css.add(url)
                            text = (folder / filename).read_text('utf-8', errors='replace')
                            pending.extend((urljoin(url, ref), category, url) for ref, category in css_dependencies(text))
                    if not pending:
                        break
                    url, category, referer = pending.popleft()
                    url = urldefrag(url)[0]
                    if url in mapping or url in attempted or not options[category] or urlsplit(url).scheme not in ('http','https'):
                        continue
                    if len(attempted) >= 5000:
                        self.log(job, 'Resource recovery capped at 5000 URLs.', 'warning')
                        break
                    attempted.add(url)
                    try:
                        final, mime, body = fetch_resource(context, url, public_url, referer=referer, timeout=min(options['timeout'],15000))
                        # Avoid misclassifying extensionless imported CSS/font resources.
                        actual = ('styles' if 'css' in mime else 'fonts' if 'font' in mime else
                                  'scripts' if 'javascript' in mime else 'images' if mime.startswith('image/') else category)
                        if options[actual]:
                            store_asset(final, mime, body, [url])
                    except Exception as exc:
                        failures.append(dict(url=url, reason=str(exc)[:250]))
                        self.log(job, 'Resource failed after retries: ' + url + ' — ' + str(exc)[:120], 'warning')
                (folder.parent / 'missing-resources.json').write_text(json.dumps(failures, indent=2), encoding='utf-8')
                self.update(job, failed_assets=len(failures))
                self.update(job, message='Rewriting links and formatting source…')
                for url, base, filename, html in pages:
                    (folder / filename).write_text(rewrite_html(html, base, mapping, options), encoding='utf-8')
                for url, (filename, mime) in assets.items():
                    path = folder / filename
                    try:
                        if 'css' in mime:
                            text = rewrite_css(path.read_text('utf-8'), url, mapping)
                            if options['beautify']:
                                import cssbeautifier
                                text = cssbeautifier.beautify(text)
                            path.write_text(text, encoding='utf-8')
                        elif ('javascript' in mime or filename.endswith('.js')) and options['beautify']:
                            import jsbeautifier
                            path.write_text(jsbeautifier.beautify(path.read_text('utf-8')), encoding='utf-8')
                    except (UnicodeError, ValueError) as exc:
                        self.log(job, 'Kept original source: ' + filename + ' — ' + str(exc)[:80], 'warning')
                (folder.parent / 'manifest.json').write_text(json.dumps(dict(source=job['url'], entry=job['entry'], urls=mapping), indent=2), encoding='utf-8')
                if job['entry']:
                    (folder.parent / 'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=files/' + job['entry'] + '"><title>Offline archive</title><a href="files/' + job['entry'] + '">Open archive</a>', encoding='utf-8')
                self.update(job, bytes=sum(f.stat().st_size for f in folder.iterdir() if f.is_file()))
                self.log(job, f'Captured {len(pages)} pages and {len(assets)} resources; {len(failures)} resources failed. Links outside the capture remain online.', 'success')
            finally:
                browser.close()
