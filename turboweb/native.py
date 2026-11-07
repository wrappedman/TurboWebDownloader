"""Narrow desktop bridge: only known project IDs, never arbitrary JS filesystem paths."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .exports import build_export


class DesktopAPI:
    def __init__(self, manager):
        self._manager = manager
        self._window = None

    def export_project(self, ident):
        try:
            if ident not in self._manager.jobs:
                raise ValueError('Unknown project.')
            job = self._manager.jobs[ident]
            source = build_export(self._manager.root, job)
            import webview
            dialog_type = webview.FileDialog.SAVE if hasattr(webview, 'FileDialog') else webview.SAVE_DIALOG
            chosen = self._window.create_file_dialog(dialog_type,
                save_filename=f'TurboWebDownloader-{ident}.zip', file_types=('ZIP archive (*.zip)',))
            if not chosen:
                return {'cancelled': True}
            path = Path(chosen[0] if isinstance(chosen, (tuple, list)) else chosen)
            if path.suffix.lower() != '.zip':
                path = path.with_suffix('.zip')
            if path.resolve() == source.resolve():
                self._manager.update(job, last_export_path=str(path))
                return {'path': str(path)}
            shutil.copyfile(source, path)
            self._manager.update(job, last_export_path=str(path))
            return {'path': str(path)}
        except Exception as exc:
            return {'error': str(exc)}

    def open_project_folder(self, ident):
        try:
            if ident not in self._manager.jobs:
                raise ValueError('Unknown project.')
            path = str((self._manager.root / ident).resolve())
            if sys.platform == 'win32':
                os.startfile(path)
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
            return {'ok': True}
        except Exception as exc:
            return {'error': str(exc)}
