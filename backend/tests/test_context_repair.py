"""Regression at Docker build-context filtering plus integrity-preserving v3 repair."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from cloud_deployment.build_genescope2 import DOCKERIGNORE
from cloud_deployment import fix_genescope2_context as patch

ROOT=Path(__file__).resolve().parents[2]

def context(root,ignore_text=DOCKERIGNORE):
    root.mkdir()
    files={'.dockerignore':ignore_text.encode(),'datasets/registry.json':b'{"datasets":[]}',
           'datasets/pancan/123/matrix.npy':b'test-only matrix bytes',
           'model_registry/id/pipeline.joblib':b'test-only model bytes',
           'deployment/models/M1.joblib':b'frozen model fixture; never deserialized'}
    for name,value in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
    meta={'schema_version':2,'release':'GeneScope2_20261103_v3','pancan_reserved_expression_included':False,
          'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
    (root/'genescope2_manifest.json').write_bytes(json.dumps(meta,ensure_ascii=False,indent=2).encode())
    return root

@pytest.fixture
def v3(tmp_path,monkeypatch):
    old=DOCKERIGNORE.replace('!datasets/registry.json\n','')
    root=context(tmp_path/'release',old)
    old_ignore=(root/'.dockerignore').read_bytes()
    old_manifest=(root/'genescope2_manifest.json').read_bytes()
    new_ignore=DOCKERIGNORE.encode()
    new_meta=json.loads(old_manifest)
    new_meta['files']['.dockerignore']=patch.digest(new_ignore)
    new_meta['context_patch']='registry-include-v1'
    new_manifest=json.dumps(new_meta,ensure_ascii=False,indent=2).encode()
    for name,value in [('OLD_IGNORE_SHA',old_ignore),('NEW_IGNORE_SHA',new_ignore),('OLD_MANIFEST_SHA',old_manifest),('NEW_MANIFEST_SHA',new_manifest)]:
        monkeypatch.setattr(patch,name,patch.digest(value))
    return root

def test_v3_repair_preserves_artifacts_and_is_idempotent(v3):
    model=v3/'deployment/models/M1.joblib';before=model.read_bytes()
    result=patch.repair(v3)
    assert result['patched'] and result['changed_manifest_entries']==['.dockerignore']
    assert model.read_bytes()==before
    assert not patch.repair(v3)['patched']
    assert Path(result['backup']).parent==v3.parent
    assert (Path(result['backup'])/'genescope2_manifest.json').is_file()

def test_v3_patch_rejects_modified_model_before_any_write(v3):
    ignore=(v3/'.dockerignore').read_bytes()
    (v3/'deployment/models/M1.joblib').write_bytes(b'changed')
    with pytest.raises(ValueError,match='摘要不符'):
        patch.repair(v3)
    assert (v3/'.dockerignore').read_bytes()==ignore

def test_v3_patch_rejects_unrecognized_manifest(v3):
    file=v3/'genescope2_manifest.json';file.write_bytes(file.read_bytes()+b' ')
    with pytest.raises(ValueError,match='已发布v3摘要'):
        patch.repair(v3)

def test_generated_rules_include_all_code_and_exclude_private_seed(tmp_path):
    if not shutil.which('node') or not (ROOT/'cloud_deployment/dist/dockerignore-check/node_modules/@balena/dockerignore').exists():
        pytest.skip('Install test-only @balena/dockerignore@1.0.2 as documented in check_context.cjs')
    root=context(tmp_path/'context')
    result=subprocess.run(['node',str(ROOT/'cloud_deployment/check_context.cjs'),str(root)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

def test_actual_docker_copy_keeps_registry_and_excludes_private_data(tmp_path):
    if not shutil.which('docker'):
        pytest.skip('Docker engine unavailable; actual COPY test runs in Linux CI')
    root=context(tmp_path/'context')
    (root/'Dockerfile').write_text('FROM scratch\nCOPY . /\n',encoding='utf-8')
    output=tmp_path/'copied'
    result=subprocess.run(['docker','buildx','build','--output',f'type=local,dest={output}',str(root)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stderr
    assert (output/'datasets/registry.json').read_bytes()==(root/'datasets/registry.json').read_bytes()
    assert (output/'deployment/models/M1.joblib').is_file()
    assert not (output/'datasets/pancan').exists()
    assert not (output/'model_registry').exists()
