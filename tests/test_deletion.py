import json
import threading

import pytest

from turboweb.app import create_app
from turboweb.engine import ArchiveManager


def project(app):
    manager = app.extensions['archives']
    job = dict(id='abc',status='completed',name='Keep me',created=0,entry='index.html')
    manager.jobs['abc'] = job
    manager.save(job)
    folder = manager.root/'abc'
    (folder/'index.html').write_text('Preserved archive')
    return manager, folder


def test_keep_files_stays_removed_after_restart(tmp_path):
    app = create_app(tmp_path)
    manager, folder = project(app)
    response = app.test_client().post('/api/projects/abc/delete',json={'delete_files':False})
    assert response.status_code == 200 and response.json['files_deleted'] is False
    assert (folder/'index.html').read_text() == 'Preserved archive'
    assert json.loads((folder/'project.json').read_text())['hidden_from_library'] is True
    assert 'abc' not in manager.jobs
    assert 'abc' not in ArchiveManager(tmp_path).jobs
    assert app.test_client().get('/api/projects').json == []


def test_delete_files_and_cache_not_external_zip(tmp_path):
    app = create_app(tmp_path/'data')
    manager, folder = project(app)
    cache = manager.root/'.exports'
    cache.mkdir()
    (cache/'abc.zip').write_bytes(b'cache')
    external = tmp_path/'saved-elsewhere.zip'
    external.write_bytes(b'keep')
    manager.jobs['abc']['last_export_path'] = str(external)
    response = app.test_client().post('/api/projects/abc/delete',json={'delete_files':True})
    assert response.status_code == 200
    assert not folder.exists() and not (cache/'abc.zip').exists()
    assert external.read_bytes() == b'keep'
    assert 'abc' not in ArchiveManager(manager.root).jobs


@pytest.mark.parametrize('body',[{}, {'delete_files':'yes'}, [], None])
def test_delete_requires_explicit_boolean(tmp_path,body):
    app = create_app(tmp_path)
    project(app)
    response = app.test_client().post('/api/projects/abc/delete',json=body,content_type='application/json')
    assert response.status_code == 400
    assert 'abc' in app.extensions['archives'].jobs


def test_active_and_finalizing_captures_cannot_be_deleted(tmp_path):
    app = create_app(tmp_path)
    manager, folder = project(app)
    client = app.test_client()
    manager.jobs['abc']['status'] = 'running'
    assert client.post('/api/projects/abc/delete',json={'delete_files':True}).status_code == 409
    manager.jobs['abc']['status'] = 'completed'
    manager.workers.add('abc')
    assert client.post('/api/projects/abc/delete',json={'delete_files':True}).status_code == 409
    assert folder.exists()
    assert client.post('/api/projects/no-such/delete',json={'delete_files':True}).status_code == 404
