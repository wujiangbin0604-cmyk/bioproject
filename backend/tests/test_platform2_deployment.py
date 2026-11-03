"""Deployment protocol checks; these do not claim a Linux container build was executed."""
import json
from pathlib import Path
import pytest
from cloud_deployment.platform2_release import verify,sha,seed_file,initialize
from cloud_deployment.platform2_gateway import render

def test_release_manifest_rejects_tampered_bytes(tmp_path):
    code=tmp_path/'app.py';code.write_text('print(1)',encoding='utf-8')
    meta={'schema_version':2,'pancan_reserved_expression_included':False,'files':{'app.py':sha(code)}}
    (tmp_path/'genescope2_manifest.json').write_text(json.dumps(meta),encoding='utf-8')
    verify(tmp_path)
    code.write_text('print(2)',encoding='utf-8')
    with pytest.raises(ValueError,match='摘要'):
        verify(tmp_path)

@pytest.mark.parametrize('unsafe',['../x','/etc/passwd','C:/x','folder\\x'])
def test_v2_manifest_rejects_paths(tmp_path,unsafe):
    (tmp_path/'genescope2_manifest.json').write_text(json.dumps({'schema_version':2,'pancan_reserved_expression_included':False,'files':{unsafe:'bad'}}),encoding='utf-8')
    with pytest.raises(ValueError,match='不安全'):
        verify(tmp_path,code_only=True)

def test_registry_required_in_image_but_private_cache_excluded():
    assert not seed_file('datasets/registry.json')
    assert seed_file('datasets/pancan/123/matrix.npy')
    assert seed_file('model_registry/model/pipeline.joblib')

def test_release_verifier_supports_ubuntu_python310_without_file_digest(tmp_path,monkeypatch):
    import hashlib
    monkeypatch.delattr(hashlib,'file_digest',raising=False)
    target=tmp_path/'sample';target.write_bytes(b'abc')
    assert sha(target)=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'

def test_gateway_preserves_auth_and_allows_v2_only_after_auth():
    text=render('47.243.232.201')
    assert text.index('basic_auth')<text.index('reverse_proxy')
    for route in ['/api/v1/experiments','/api/v1/experiments/*/cancel','/api/v1/datasets/import']:
        assert route in text
    assert '127.0.0.1:18080' in text
    assert 'write 0' in text and 'max_conns_per_host 16' in text
    assert 'import /etc/genescope/users.caddy' in text
    assert 'respond @bad_origin' in text
    assert 'tls internal' not in text

def test_seeding_refuses_unmarked_nonempty_directory(tmp_path):
    root=tmp_path/'release';root.mkdir()
    (root/'genescope2_manifest.json').write_text(json.dumps({'schema_version':2,'pancan_reserved_expression_included':False,'files':{}}),encoding='utf-8')
    state=tmp_path/'existing';state.mkdir();(state/'unrelated.txt').write_text('keep',encoding='utf-8')
    with pytest.raises(ValueError,match='非空目录'):
        initialize(root,state)
    assert (state/'unrelated.txt').read_text()=='keep'
