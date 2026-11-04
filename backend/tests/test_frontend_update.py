"""Static update boundaries and rollback, using synthetic bytes rather than model loading."""
import hashlib
import json
from pathlib import Path
import pytest
from cloud_deployment.update_frontend import apply_update, read_release, rollback


def put(root, name, content):
    path=root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def pair(tmp_path):
    root, payload = tmp_path/'release', tmp_path/'update'
    old={name:put(root,name,value) for name,value in {'frontend/dist/index.html':b'old', 'frontend/dist/assets/old.js':b'old-js', 'backend/api.py':b'protected API', 'model_registry/model.joblib':b'protected model', 'datasets/data.npy':b'protected data'}.items()}
    (root/'genescope2_manifest.json').write_text(json.dumps({'schema_version':2,'pancan_reserved_expression_included':False,'files':old}),encoding='utf-8')
    files={name:put(payload,name,value) for name,value in {'frontend/dist/index.html':b'new', 'frontend/dist/assets/new.js':b'new-js'}.items()}
    (payload/'frontend_update.json').write_text(json.dumps({'schema_version':1,'scope':'frontend/dist','release':'ui-test','created_at':'test','files':files}),encoding='utf-8')
    return root,payload


def test_dry_run_does_not_modify_release(pair):
    root,payload=pair
    before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert apply_update(payload,root)['dry_run']
    assert before=={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_apply_and_rollback_preserve_every_nonfrontend_digest(pair):
    root,payload=pair
    old=read_release(root)
    applied=apply_update(payload,root,True)
    new=read_release(root)
    assert {k:v for k,v in old['files'].items() if not k.startswith('frontend/')}=={k:v for k,v in new['files'].items() if not k.startswith('frontend/')}
    assert not (root/'frontend/dist/assets/old.js').exists()
    assert Path(applied['backup']).parent==root.parent
    rollback(root,applied['backup'])
    assert read_release(root)==old
    assert (root/'frontend/dist/index.html').read_bytes()==b'old'


@pytest.mark.parametrize('target', ['backend/api.py','model_registry/model.joblib','datasets/data.npy','frontend/dist/index.html'])
def test_tampered_release_is_rejected_before_writing(pair,target):
    root,payload=pair
    (root/target).write_bytes(b'tampered')
    before=(root/'genescope2_manifest.json').read_bytes()
    with pytest.raises(ValueError,match='原发布文件校验失败'):
        apply_update(payload,root,True)
    assert (root/'genescope2_manifest.json').read_bytes()==before


@pytest.mark.parametrize('kind',['tamper','extra','escape','nonfrontend'])
def test_invalid_payload_rejected_before_writing(pair,kind):
    root,payload=pair
    path=payload/'frontend_update.json'
    info=json.loads(path.read_text())
    if kind=='tamper': (payload/'frontend/dist/index.html').write_bytes(b'tamper')
    if kind=='extra': put(payload,'frontend/dist/extra.js',b'extra')
    if kind in ['escape','nonfrontend']: info['files']['frontend/dist/../../backend/api.py' if kind=='escape' else 'backend/api.py']='bad'
    path.write_text(json.dumps(info))
    with pytest.raises(ValueError): apply_update(payload,root,True)
    assert (root/'frontend/dist/index.html').read_bytes()==b'old'
