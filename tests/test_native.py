import sys
import zipfile
from types import SimpleNamespace

from turboweb.engine import ArchiveManager
from turboweb.native import DesktopAPI


def make_bridge(tmp_path):
    manager = ArchiveManager(tmp_path)
    manager.jobs['abc'] = dict(id='abc', status='completed', entry='start.html')
    folder = tmp_path/'abc'
    (folder/'files').mkdir(parents=True)
    (folder/'files'/'start.html').write_text('offline')
    (folder/'index.html').write_text('entry')
    return DesktopAPI(manager)


def test_native_save_zip(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path/'chosen.zip'
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: (str(target),))
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(FileDialog=SimpleNamespace(SAVE='save')))
    assert bridge.export_project('abc') == {'path':str(target)}
    with zipfile.ZipFile(target) as archive:
        assert archive.read('files/start.html') == b'offline'
    assert (tmp_path/'.exports'/'abc.zip').exists()
    assert bridge._manager.jobs['abc']['last_export_path'] == str(target)


def test_native_cancel_and_unknown_id(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(FileDialog=SimpleNamespace(SAVE='save')))
    assert bridge.export_project('abc') == {'cancelled':True}
    assert bridge.export_project('../../bad') == {'error':'Unknown project.'}
    assert bridge.open_project_folder('../../bad') == {'error':'Unknown project.'}
