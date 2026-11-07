"""URL-shaped, Windows-safe archive paths with collision protection."""
import hashlib
import mimetypes
import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit


def short_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:10]


def safe_segment(value):
    value = unquote(value)
    # Encode separators, percent signs and reserved Windows characters, not normal names.
    text = ''.join(''.join(f'%{b:02X}' for b in char.encode())
                   if char in '<>:"/\\|?*%' or ord(char) < 32 else char for char in value)
    if text in ('', '.', '..'):
        text = ''.join(f'%{ord(c):02X}' for c in text) or '_'
    while text.endswith(('.', ' ')):
        last = text[-1]
        text = text[:-1] + f'%{ord(last):02X}'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', text, re.I):
        text = '_' + text
    if len(text) > 80:
        suffix = PurePosixPath(text).suffix[:12]
        text = text[:50] + '__' + short_hash(value) + suffix
    return text


def add_suffix(path, suffix):
    item = PurePosixPath(path)
    return str(item.with_name(item.stem + suffix + item.suffix))


def website_path(url, content_type='', page=False):
    parts = urlsplit(url)
    host = safe_segment(parts.netloc.lower())
    segments = [safe_segment(part) for part in parts.path.split('/') if part]
    if not segments or parts.path.endswith('/'):
        segments.append('index.html' if page else 'index')
    elif page and not PurePosixPath(segments[-1]).suffix:
        segments.append('index.html')
    elif page and PurePosixPath(segments[-1]).suffix.lower() not in ('.html', '.htm', '.xhtml'):
        # Rendered server routes need a browser-readable HTML extension.
        segments[-1] += '.html'
    if not page:
        mime = content_type.split(';')[0].strip().lower()
        ext = mimetypes.guess_extension(mime) or ''
        if ext == '.jpe':
            ext = '.jpg'
        suffix = PurePosixPath(segments[-1]).suffix.lower()
        needs_extension = not suffix
        if 'css' in mime and suffix != '.css':
            needs_extension = True
        if 'javascript' in mime and suffix not in ('.js', '.mjs', '.cjs'):
            needs_extension = True
        if needs_extension and ext:
            segments[-1] += ext
    result = '/'.join([host, *segments])
    if parts.query:
        result = add_suffix(result, '__q_' + short_hash(parts.query))
    if len(result) > 180:
        tail = segments[-1]
        if parts.query:
            tail = add_suffix(tail, '__q_' + short_hash(parts.query))
        if len(tail) > 64:
            tail = tail[:35] + '__' + short_hash(url) + PurePosixPath(tail).suffix[:12]
        result = '/'.join([host, '_longpaths', short_hash(parts.path), tail])
    return result


class WebsiteLayout:
    def __init__(self):
        self.urls = {}
        self.files = set()
        self.directories = set()

    def allocate(self, url, content_type='', page=False):
        key = (url, page)
        if key in self.urls:
            return self.urls[key]
        candidate = website_path(url, content_type, page)
        components = candidate.split('/')
        # A URL can be both a file and a directory prefix on a server, not on disk.
        for i in range(1, len(components)):
            prefix = '/'.join(components[:i]).casefold()
            if prefix in self.files:
                components[i-1] += '__dir_' + short_hash('/'.join(components[:i]))
        candidate = '/'.join(components)
        original = candidate
        attempt = 0
        while candidate.casefold() in self.files or candidate.casefold() in self.directories:
            attempt += 1
            candidate = add_suffix(original, '__' + short_hash(url + str(page) + str(attempt)))
        self.files.add(candidate.casefold())
        for parent in PurePosixPath(candidate).parents:
            if str(parent) != '.':
                self.directories.add(str(parent).casefold())
        self.urls[key] = candidate
        return candidate


def relative_url(target, source):
    relative = posixpath.relpath(target, posixpath.dirname(source) or '.')
    # Filenames are filesystem paths; encode #, %, spaces, Unicode etc. for links.
    return quote(relative, safe='/.-_~')
