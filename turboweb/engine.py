"""Bounded browser-based archiver. No target server source is retrieved."""
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import socket
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

ASSET_TYPES = {'stylesheet': 'styles', 'script': 'scripts', 'image': 'images', 'font': 'fonts', 'media': 'media'}
DEFAULTS = dict(max_pages=25, depth=2, delay=500, timeout=30000, images=True,
                styles=True, scripts=True, fonts=True, media=False, beautify=True,
                run_scripts=False, respect_robots=True)


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
        for attr in ('href', 'src', 'poster', 'action', 'data-src'):
            if el.has_attr(attr):
                el[attr] = local_ref(el[attr], base, mapping)
        for attr in ('integrity', 'crossorigin', 'nonce'):
            el.attrs.pop(attr, None)
        if el.has_attr('srcset') and not el['srcset'].lstrip().startswith('data:'):
            el['srcset'] = ', '.join(' '.join([local_ref(p.split()[0], base, mapping), *p.split()[1:]]) for p in el['srcset'].split(',') if p.split())
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
        self.root = Path(root)
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
                   message='Waiting for browser…', entry=None)
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
                self.update(job, status=status, message='Capture stopped; partial archive retained.' if event.is_set() else ('Archive ready to explore.' if job['pages'] else 'No pages could be captured. See the activity log.'))
            except Exception as exc:
                self.log(job, str(exc), 'error')
                self.update(job, status='failed', message='Capture failed. See the activity log for details.')
            finally:
                folder = self.root / job['id']
                (folder / 'report.json').write_text(json.dumps(job, indent=2), encoding='utf-8')

    def capture(self, job, event):
        from playwright.sync_api import sync_playwright
        from urllib.robotparser import RobotFileParser
        options = job['options']
        folder = self.root / job['id'] / 'files'
        folder.mkdir(exist_ok=True)
        mapping, assets, pages = {}, {}, []
        queue = deque([(job['url'], 0)])
        seen = set()
        origin = urlsplit(job['url']).netloc
        robots = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=os.environ.get('TURBOWEB_CHROMIUM') or None, args=['--disable-dev-shm-usage'])
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
                        robots.parse(response.text().splitlines())
                    elif response and response.status in (401, 403):
                        raise ValueError('robots.txt access denied; capture stopped to respect site policy.')
                except ValueError:
                    raise
                except Exception as exc:
                    self.log(job, 'Could not read robots.txt: ' + str(exc)[:160], 'warning')

            total = [0]
            def response_received(response):
                if event.is_set() or response.request.resource_type not in ASSET_TYPES or not response.ok:
                    return
                category = ASSET_TYPES[response.request.resource_type]
                if not options[category]:
                    return
                url = urldefrag(response.url)[0]
                if url in assets:
                    return
                try:
                    # Avoid accidentally filling the disk with large streaming responses.
                    if int(response.headers.get('content-length', 0)) > 25 * 1024 * 1024:
                        self.log(job, 'Skipped large resource: ' + url, 'warning')
                        return
                    body = response.body()
                    if len(body) > 25 * 1024 * 1024 or total[0] + len(body) > 500 * 1024 * 1024:
                        self.log(job, 'Resource size budget exceeded: ' + url, 'warning')
                        return
                    mime = response.headers.get('content-type', '')
                    filename = file_name(url, mime)
                    (folder / filename).write_bytes(body)
                    assets[url] = (filename, mime)
                    mapping[url] = filename
                    total[0] += len(body)
                    self.update(job, assets=len(assets), bytes=total[0])
                except Exception as exc:
                    self.log(job, 'Resource unavailable: ' + url + ' — ' + str(exc)[:100], 'warning')
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
                        response = page.goto(url, wait_until='domcontentloaded')
                        if response and response.status >= 400:
                            raise ValueError('HTTP ' + str(response.status))
                        try:
                            page.wait_for_load_state('networkidle', timeout=min(5000, options['timeout']))
                        except Exception:
                            pass
                        # Trigger common lazy loading without an unbounded infinite scroll.
                        for _ in range(4):
                            if event.is_set():
                                break
                            page.evaluate('window.scrollBy(0, window.innerHeight)')
                            page.wait_for_timeout(180)
                        page.evaluate('window.scrollTo(0, 0)')
                        page.wait_for_timeout(options['delay'])
                        final_url = normalize_url(page.url)
                        if urlsplit(final_url).netloc != origin:
                            self.log(job, 'Skipped page redirected outside the target site.', 'warning')
                            continue
                        base = page.evaluate('document.baseURI')
                        html = page.content()
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
                                    if urlsplit(link).netloc == origin and link not in seen and len(queue) < 3000:
                                        queue.append((link, depth + 1))
                                except ValueError:
                                    pass
                    except Exception as exc:
                        self.update(job, failed=job['failed'] + 1)
                        self.log(job, 'Page failed: ' + url + ' — ' + str(exc)[:220], 'error')
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
                self.log(job, f'Captured {len(pages)} pages and {len(assets)} resources. Links outside the capture remain online.', 'success')
            finally:
                browser.close()
