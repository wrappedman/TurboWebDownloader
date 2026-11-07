import io
import zipfile

import pytest
from turboweb.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


def test_home_and_static(client):
    assert b'TurboWebDownloader' in client.get('/').data
    assert client.get('/static/logo.svg').status_code == 200
    assert client.get('/static/app.ico').status_code == 200
    assert client.get('/api/projects').json == []


@pytest.mark.parametrize('body', [{}, {'name':'Test','url':'file:///etc/passwd'}, {'name':'x','url':'https://example.com','options':{'depth':11}}, {'name':'x','url':'https://example.com','options':{'max_pages':True}}, {'name':'x','url':'https://example.com','options':{'images':'yes'}}, {'name':'x','url':'https://example.com','options':[]}])
def test_validation(client, body):
    assert client.post('/api/projects', json=body).status_code == 400


def test_cross_origin_protection(client):
    assert client.post('/api/projects', json={}, headers={'Origin':'https://evil.test'}).status_code == 403
    assert client.post('/api/projects', data='{}').status_code == 415


def test_creation(client, app, monkeypatch):
    manager = app.extensions['archives']
    monkeypatch.setattr(manager, 'create', lambda name,url,options: dict(id='test',name=name,url=url,options=options))
    response = client.post('/api/projects', json=dict(name='Docs', url='https://example.com',options={'depth':0}))
    assert response.status_code == 201
    assert response.json['options']['depth'] == 0
    assert response.json['options']['images'] is True
    assert response.json['url'] == 'https://example.com/'


def test_export_and_archive_isolation(client, app):
    manager = app.extensions['archives']
    manager.jobs['abc'] = dict(id='abc',status='completed',entry='start.html')
    folder = manager.root/'abc'
    (folder/'files').mkdir(parents=True)
    (folder/'files'/'start.html').write_text('<h1>offline</h1>')
    (folder/'index.html').write_text('start')
    (folder/'project.json').write_text('private app metadata')
    response = client.get('/api/projects/abc/export')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert 'files/start.html' in archive.namelist()
        assert 'READ ME.txt' in archive.namelist()
        assert 'project.json' not in archive.namelist()
    response = client.get('/archive/abc/files/start.html')
    assert response.status_code == 200
    assert 'sandbox allow-scripts;' in response.headers['Content-Security-Policy']
    assert 'allow-same-origin' not in response.headers['Content-Security-Policy']
    assert client.get('/archive/abc/../../LICENSE').status_code == 404
    manager.jobs['abc']['status'] = 'running'
    assert client.get('/api/projects/abc/export').status_code == 409


def test_unknown_project(client):
    assert client.post('/api/projects/missing/cancel', json={}).status_code == 404
    assert client.get('/api/projects/missing/export').status_code == 404
