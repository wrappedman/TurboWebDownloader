"""Bounded requests, resource discovery and lazy-render preparation."""
import re
import time
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

RESOURCE_LIMIT = 25 * 1024 * 1024
TOTAL_LIMIT = 500 * 1024 * 1024


def fetch_resource(context, url, validate, referer=None, retries=2, limit=RESOURCE_LIMIT, timeout=15000):
    """Check every redirect, use session cookies, retry transient failures only."""
    last = None
    for attempt in range(retries + 1):
        current = url
        try:
            for _ in range(6):
                validate(current)
                response = context.request.get(current, headers={'Referer': referer} if referer else {},
                                               timeout=timeout, max_redirects=0)
                try:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get('location')
                        if not location:
                            raise ValueError('Redirect has no Location header')
                        current = urljoin(current, location)
                        continue
                    if response.status == 429 or response.status >= 500:
                        raise OSError('HTTP ' + str(response.status))
                    if not response.ok:
                        raise ValueError('HTTP ' + str(response.status))
                    if int(response.headers.get('content-length', 0)) > limit:
                        raise ValueError('Resource exceeds size limit')
                    body = response.body()
                    if len(body) > limit:
                        raise ValueError('Resource exceeds size limit')
                    return current, response.headers.get('content-type', ''), body
                finally:
                    response.dispose()
            raise ValueError('Too many redirects')
        except ValueError:
            raise
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(min(.3 * (2 ** attempt), 1.2))
    raise OSError(str(last))


def srcset_items(value):
    # A data URL may contain commas. Never split its payload into fake URLs.
    for match in re.finditer(r'(data:[^\s]+|[^\s,]+)(?:\s+([\d.]+[wx]))?\s*(?:,|$)', value):
        url = match[1].rstrip(',')
        if url:
            yield url, match[2] or ''


def css_refs(text):
    refs = [m[2].strip() for m in re.finditer(r'url\(\s*([\'"]?)(.*?)\1\s*\)', text, re.I)]
    refs += [m[2] for m in re.finditer(r'@import\s+([\'"])(.*?)\1', text, re.I)]
    return refs


def css_dependencies(text):
    imports = {m[2] or m[4] for m in re.finditer(
        r'@import\s+(?:url\(\s*([\'"]?)(.*?)\1\s*\)|([\'"])(.*?)\3)', text, re.I)}
    font_refs = set()
    for block in re.findall(r'@font-face\s*\{(.*?)\}', text, re.I | re.S):
        font_refs.update(css_refs(block))
    for ref in css_refs(text):
        yield ref, 'styles' if ref in imports else 'fonts' if ref in font_refs else resource_category(ref)


def snapshot_html(page):
    # CSS-in-JS libraries often populate CSSOM rules without style text nodes.
    page.evaluate('''() => {
      for (const sheet of Array.from(document.styleSheets)) {
        try {
          if (sheet.ownerNode && sheet.ownerNode.tagName === 'STYLE') {
            const text = Array.from(sheet.cssRules, rule => rule.cssText).join('\\n');
            if (text) sheet.ownerNode.textContent = text;
          }
        } catch (_) { /* Cross-origin linked stylesheets are captured separately. */ }
      }
      for (const sheet of (document.adoptedStyleSheets || [])) {
        const style = document.createElement('style');
        style.textContent = Array.from(sheet.cssRules, rule => rule.cssText).join('\\n');
        document.head.appendChild(style);
      }
    }''')
    return page.content()


def resource_category(url, default='images'):
    ext = urlsplit(url).path.lower().rsplit('.', 1)[-1]
    return {'css':'styles', 'js':'scripts', 'mjs':'scripts', 'woff':'fonts', 'woff2':'fonts',
            'ttf':'fonts', 'otf':'fonts', 'eot':'fonts', 'mp4':'media', 'webm':'media',
            'mp3':'media', 'ogg':'media', 'wav':'media'}.get(ext, default)


def html_resources(html, base):
    soup = BeautifulSoup(html, 'html.parser')
    refs = []
    for el in soup.find_all(True):
        if el.name in ('img', 'source', 'video', 'audio', 'image', 'input'):
            for attr in ('src', 'poster', 'data-src', 'data-original', 'data-lazy-src', 'href', 'xlink:href'):
                if el.get(attr):
                    refs.append((el[attr], 'media' if (el.name in ('video','audio') or (el.name == 'source' and el.parent and el.parent.name in ('video','audio'))) and attr == 'src' else 'images'))
            for attr in ('srcset', 'data-srcset'):
                refs.extend((url, 'images') for url, _ in srcset_items(el.get(attr, '')))
        if el.name == 'link' and el.get('href'):
            rel = el.get('rel', [])
            if 'stylesheet' in rel:
                refs.append((el['href'], 'styles'))
            elif any('icon' in r for r in rel):
                refs.append((el['href'], 'images'))
            elif el.get('as') in ('font', 'image', 'style', 'script'):
                refs.append((el['href'], {'font':'fonts','image':'images','style':'styles','script':'scripts'}[el['as']]))
        if el.name == 'script' and el.get('src'):
            refs.append((el['src'], 'scripts'))
        text = el.get('style', '')
        if el.name == 'style':
            text += el.get_text()
        refs.extend(css_dependencies(text))
    for ref, category in refs:
        absolute = urldefrag(urljoin(base, ref))[0]
        if urlsplit(absolute).scheme in ('http', 'https'):
            yield absolute, category


def prepare_page(page, event, max_scrolls=40):
    """Activate common lazy images; scroll until bottom stabilizes or bounded budget."""
    page.evaluate('''() => {
      document.querySelectorAll('img,source').forEach(el => {
        const lazy = el.dataset.src || el.dataset.original || el.dataset.lazySrc;
        if (lazy) el.src = lazy;
        if (el.dataset.srcset) el.srcset = el.dataset.srcset;
        if (el.tagName === 'IMG') { el.loading = 'eager'; el.fetchPriority = 'high'; }
      });
    }''')
    stable = 0
    for _ in range(max_scrolls):
        if event.is_set():
            break
        result = page.evaluate('''() => {
          window.scrollBy(0, Math.max(300, innerHeight * .8));
          return {bottom: scrollY + innerHeight >= document.documentElement.scrollHeight - 4,
                  height: document.documentElement.scrollHeight};
        }''')
        page.wait_for_timeout(160)
        height = page.evaluate('document.documentElement.scrollHeight')
        stable = stable + 1 if result['bottom'] and result['height'] == height else 0
        if stable >= 3:
            break
    page.evaluate('window.scrollTo(0, 0)')
    if not event.is_set():
        page.evaluate('''() => Promise.race([
          Promise.all([document.fonts ? document.fonts.ready : Promise.resolve(),
            ...Array.from(document.images, img => img.decode ? img.decode().catch(() => {}) : Promise.resolve())]),
          new Promise(resolve => setTimeout(resolve, 4000))
        ])''')
    return stable >= 3
