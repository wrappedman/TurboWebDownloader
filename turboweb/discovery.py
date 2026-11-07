"""Bounded preflight discovery: sitemaps plus real rendered navigation, not a fake total."""
import copy
import gzip
import threading
import time
import uuid
from collections import deque
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from .browser import launch_browser
from .capture_tools import fetch_resource

MAX_URLS = 10000


def sitemap_urls(context, start, validate, robots_text='', stop=None):
    from .engine import normalize_url
    origin = urlsplit(start).netloc
    queue = deque([urljoin(start, '/sitemap.xml')])
    for line in robots_text.splitlines():
        if line.lower().startswith('sitemap:'):
            queue.append(line.split(':', 1)[1].strip())
    seen, urls, warnings = set(), set(), []
    deadline = time.monotonic() + 30
    while queue and len(seen) < 20 and len(urls) < MAX_URLS and time.monotonic() < deadline and not (stop and stop.is_set()):
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        try:
            final, mime, body = fetch_resource(context, url, validate, retries=0, limit=5*1024*1024, timeout=3000)
            if body.startswith(b'\x1f\x8b'):
                # Read at most 5 MB of decompressed sitemap data.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                    body = stream.read(5*1024*1024 + 1)
                if len(body) > 5*1024*1024:
                    raise ValueError('Decompressed sitemap exceeds limit')
            root = ElementTree.fromstring(body)
            tag = root.tag.rsplit('}', 1)[-1]
            if tag not in ('urlset', 'sitemapindex'):
                raise ValueError('Not a sitemap document')
            # Only direct page <loc> elements, never image/video sitemap <loc>.
            for child in root:
                loc = next((el.text for el in child if el.tag.rsplit('}',1)[-1] == 'loc'), None)
                if not loc:
                    continue
                link = normalize_url(urljoin(final, loc))
                if tag == 'sitemapindex':
                    if len(queue) < 100:
                        queue.append(link)
                elif urlsplit(link).netloc == origin:
                    urls.add(link)
                    if len(urls) >= MAX_URLS:
                        break
        except Exception as exc:
            warnings.append('Sitemap unavailable: ' + url + ' — ' + str(exc)[:120])
    return sorted(urls), warnings, bool(queue) or len(urls) >= MAX_URLS


class DiscoveryService:
    def __init__(self, manager):
        self.manager = manager
        self.tasks = {}
        self.lock = threading.RLock()

    def snapshot(self, ident):
        with self.lock:
            return copy.deepcopy(self.tasks[ident]['result'])

    def create(self, url, limit=50, depth=3, respect=True):
        with self.lock:
            if sum(t['result']['status'] in ('queued','running') for t in self.tasks.values()) >= 2:
                raise ValueError('Two analyses are already queued or running. Stop one or wait.')
            for ident in list(self.tasks):
                if len(self.tasks) < 20:
                    break
                if self.tasks[ident]['result']['status'] not in ('queued','running'):
                    del self.tasks[ident]
            ident = uuid.uuid4().hex[:12]
            result = dict(id=ident, url=url, status='queued', discovered=1, inspected=0,
                          sitemap_count=0, limit=limit, depth=depth, bounded=True, warnings=[],
                          urls=[url], message='Waiting for the capture browser…')
            event = threading.Event()
            self.tasks[ident] = dict(result=result, event=event)
            threading.Thread(target=self.run, args=(ident,url,limit,depth,respect,event), daemon=True).start()
            return copy.deepcopy(result)

    def update(self, ident, **changes):
        with self.lock:
            self.tasks[ident]['result'].update(changes)

    def run(self, ident, url, limit, depth, respect, event):
        from playwright.sync_api import sync_playwright
        from .engine import normalize_url, public_url
        warnings = []
        try:
            with self.manager.gate, sync_playwright() as p:
                if event.is_set():
                    self.update(ident, status='cancelled', message='Analysis cancelled; counts are partial.')
                    return
                self.update(ident, status='running', message='Reading robots.txt and sitemaps…')
                browser, _ = launch_browser(p)
                try:
                    context = browser.new_context(service_workers='block')
                    def guard(route):
                        try:
                            public_url(route.request.url)
                            if event.is_set() or route.request.resource_type in ('image','font','media'):
                                route.abort()
                            else:
                                route.continue_()
                        except Exception:
                            route.abort()
                    context.route('**/*', guard)
                    robots_text, robots = '', None
                    try:
                        _, _, body = fetch_resource(context, urljoin(url, '/robots.txt'), public_url, retries=0, timeout=10000, limit=1024*1024)
                        robots_text = body.decode('utf-8', errors='replace')
                        robots = RobotFileParser()
                        robots.parse(robots_text.splitlines())
                    except Exception as exc:
                        if respect and any(code in str(exc) for code in ('HTTP 401','HTTP 403')):
                            raise ValueError('robots.txt access denied; analysis stopped.')
                        warnings.append('robots.txt unavailable: ' + str(exc)[:120])
                    urls, notes, bounded = sitemap_urls(context, url, public_url, robots_text, event)
                    warnings.extend(notes)
                    known = set(urls) | {url}
                    self.update(ident, sitemap_count=len(urls), discovered=len(known), urls=sorted(known), warnings=warnings)
                    queue = deque([(url,0)])
                    scheduled = {url}
                    for link in urls[:limit]:
                        if link not in scheduled and depth > 0:
                            queue.append((link,1)); scheduled.add(link)
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    inspected = 0
                    origin = urlsplit(url).netloc
                    deadline = time.monotonic() + 120
                    while queue and inspected < limit and not event.is_set() and time.monotonic() < deadline:
                        link, level = queue.popleft()
                        if respect and robots and not robots.can_fetch('TurboWebDownloader', link):
                            continue
                        inspected += 1
                        self.update(ident, inspected=inspected, message='Inspecting ' + link)
                        try:
                            response = page.goto(link, wait_until='domcontentloaded')
                            if response and response.status >= 400:
                                raise ValueError('HTTP ' + str(response.status))
                            try:
                                page.wait_for_load_state('networkidle', timeout=2000)
                            except Exception:
                                pass
                            page.wait_for_timeout(250)
                            # Adopt the landing hostname only for the first page (e.g. www redirect).
                            origin = urlsplit(page.url).netloc if inspected == 1 else origin
                            for href in page.locator('a[href]').evaluate_all('(nodes) => nodes.map(n => n.href)'):
                                try:
                                    candidate = normalize_url(href)
                                    if urlsplit(candidate).netloc != origin:
                                        continue
                                    if len(known) < MAX_URLS:
                                        known.add(candidate)
                                    if candidate not in scheduled and level < depth and len(scheduled) < 3000:
                                        scheduled.add(candidate); queue.append((candidate, level+1))
                                except ValueError:
                                    pass
                        except Exception as exc:
                            warnings.append('Page unavailable: ' + link + ' — ' + str(exc)[:100])
                        self.update(ident, discovered=len(known), urls=sorted(known), warnings=warnings[-50:])
                    self.update(ident, status='cancelled' if event.is_set() else 'completed',
                        bounded=bounded or bool(queue) or len(known)>=MAX_URLS,
                        message='Discovery finished. This is a known-URL count, not a guaranteed site total.', warnings=warnings[-50:])
                finally:
                    browser.close()
        except Exception as exc:
            self.update(ident, status='failed', message=str(exc))
