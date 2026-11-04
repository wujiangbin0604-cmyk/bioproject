"""本地入口的路由边界、发布完整性和CLI错误反馈。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from local_runtime.app import create_local_app
from local_runtime.integrity import verify
from scripts.build_local_bundle import public_path


@pytest.fixture
def local_app(tmp_path):
    frontend=tmp_path/'frontend/dist'
    (frontend/'assets').mkdir(parents=True)
    (frontend/'index.html').write_text('<!doctype html><title>Local app fixture</title>')
    (frontend/'assets/app.js').write_text('console.log("fixture")')
    return create_local_app(tmp_path)


def test_same_port_preserves_api_and_spa_refresh(local_app):
    with TestClient(local_app) as client:
        assert client.get('/api/v1/health').json()['data']['api']=='ok'
        assert client.get('/api/v1/datasets').json()['items'][0]['status']=='pending'
        for route in ['/', '/lab', '/monitor/unknown', '/features']:
            assert 'Local app fixture' in client.get(route).text
        assert client.get('/assets/app.js').headers['content-type'].startswith('text/javascript')


@pytest.mark.parametrize('path',['/api/v1/missing','/assets/missing.js','/missing.json','/deployment/models/M1_anova_top50.joblib'])
def test_missing_api_and_files_never_become_html_success(local_app,path):
    with TestClient(local_app) as client:
        response=client.get(path)
        assert response.status_code==404
        assert 'Local app fixture' not in response.text


def test_manifest_fails_on_modified_content_and_unsafe_paths(tmp_path):
    file=tmp_path/'genescope.py';file.write_bytes(b'reviewed fixture')
    metadata={'schema_version':1,'version':'test','raw_data_included':False,'files':{'genescope.py':hashlib.sha256(file.read_bytes()).hexdigest()}}
    manifest=tmp_path/'local_bundle_manifest.json'
    manifest.write_text(json.dumps(metadata))
    assert verify(tmp_path)['verified_files']==1
    file.write_bytes(b'changed')
    with pytest.raises(ValueError,match='校验失败'): verify(tmp_path)
    metadata['files']={'../escape':'bad'};manifest.write_text(json.dumps(metadata))
    with pytest.raises(ValueError,match='不安全路径'): verify(tmp_path)


@pytest.mark.parametrize('path',['.env','backend/.vendor314/package.py','datasets/gse45827/raw/matrix.txt.gz','data/data.csv','results/scores.csv','model_registry/model/pipeline.joblib','experiment_runs/task/state.json','source.tar.gz'])
def test_local_package_excludes_runtime_and_private_data(path):
    assert not public_path(path)


def test_source_paths_and_trusted_m1_can_ship():
    for path in ['genescope.py','datasets/registry.json','data/split_manifest.json','deployment/models/M1_anova_top50.joblib','deployment/examples/sample_input.csv']:
        assert public_path(path)


def test_cli_rejects_invalid_port_without_starting_service():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,str(root/'genescope.py'),'--port','80','--current-env'],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==2
    assert '1024' in result.stderr
