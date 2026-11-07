"""Disk-backed ZIP exports shared by the browser and native Save As bridge."""
import os
import tempfile
import threading
import zipfile
from pathlib import Path

LOCK = threading.Lock()
ACTIVE = ('queued', 'running', 'stopping')


def build_export(root, job):
    root = Path(root)
    if job['status'] in ACTIVE or not job.get('entry'):
        raise ValueError('Wait for a finished capture before exporting.')
    folder = root / job['id']
    if not (folder / 'files' / job['entry']).is_file():
        raise ValueError('The captured entry page is missing from disk. Capture this project again.')
    exports = root / '.exports'
    exports.mkdir(exist_ok=True)
    target = exports / (job['id'] + '.zip')
    with LOCK:
        # A stopped/completed project is immutable; its export can be reused.
        files = [f for f in folder.rglob('*') if f.is_file() and not f.is_symlink() and f.name not in ('project.json', 'project.tmp')]
        if target.is_file() and target.stat().st_mtime >= max(f.stat().st_mtime for f in files):
            return target
        fd, temp = tempfile.mkstemp(suffix='.zip', dir=exports)
        os.close(fd)
        try:
            with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for file in files:
                    archive.write(file, file.relative_to(folder))
                archive.writestr('READ ME.txt', 'TurboWebDownloader offline archive\nOpen index.html in a browser. For best compatibility, serve this folder with: python -m http.server 8080\nOnly captured pages and resources work offline. Forms, APIs, logins and uncaptured links may require the original website.\n')
            Path(temp).replace(target)
        finally:
            Path(temp).unlink(missing_ok=True)
    return target
