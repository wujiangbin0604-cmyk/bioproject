"""Repair the exact published v3 Docker ignore file; keep every model/data hash unchanged.

Runs with Ubuntu Python 3.10. No dependencies, model loading, training, deletion or Docker commands.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

OLD_IGNORE_SHA='3d897a54348075f6aceb787334daeb436d54d87305c1e0067897022e39eddaea'
NEW_IGNORE_SHA='df5d1ce138d521102f2e420e64ef9a66152c9241780447ef5f94c1201d1a7865'
OLD_MANIFEST_SHA='9b324f8aca4306d58f29de21d886ebaa9923e4aa32c0f528df85b80d99198a54'
NEW_MANIFEST_SHA='2aadc7a64ec7bfd152fd36c30883f41afcecd36abbfcd25d2875e42f6f6220a9'

def digest(content):
    return hashlib.sha256(content).hexdigest()

def verify_files(root,manifest):
    for relative,expected in manifest['files'].items():
        part=PurePosixPath(relative)
        if not part.parts or part.is_absolute() or '..' in part.parts or ':' in relative or '\\' in relative:
            raise ValueError('发布清单路径无效')
        target=root.joinpath(*part.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
            raise ValueError(f'发布文件不存在或路径无效：{relative}')
        hasher=hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                hasher.update(block)
        if hasher.hexdigest()!=expected:
            raise ValueError(f'原文件摘要不符，未执行补丁：{relative}')

def atomic_bytes(path,content):
    temp=path.with_name(path.name+'.contextfix.tmp')
    with temp.open('xb') as stream:
        stream.write(content)
    os.replace(temp,path)

def repair(directory):
    directory=Path(directory)
    if directory.is_symlink():
        raise ValueError('发布目录不能是符号链接')
    root=directory.resolve(strict=True)
    manifest_path=root/'genescope2_manifest.json'
    ignore_path=root/'.dockerignore'
    before_manifest=manifest_path.read_bytes()
    before_ignore=ignore_path.read_bytes()
    manifest=json.loads(before_manifest)
    if manifest.get('release')!='GeneScope2_20261103_v3':
        raise ValueError('该补丁仅适用于原始GeneScope2_20261103_v3发布包')
    if digest(before_manifest)==NEW_MANIFEST_SHA and digest(before_ignore)==NEW_IGNORE_SHA:
        verify_files(root,manifest)
        return {'patched':False,'message':'补丁已应用，全部发布摘要通过','files_verified':len(manifest['files'])}
    if digest(before_manifest)!=OLD_MANIFEST_SHA or digest(before_ignore)!=OLD_IGNORE_SHA:
        raise ValueError('文件与已发布v3摘要不一致，拒绝覆盖；请保留错误输出')
    verify_files(root,manifest)
    ending=b'\r\n' if b'\r\n' in before_ignore else b'\n'
    old_line=b'datasets/*/'+ending
    if before_ignore.count(old_line)!=1:
        raise ValueError('排除规则不符合原发布包')
    after_ignore=before_ignore.replace(old_line,old_line+b'!datasets/registry.json'+ending)
    manifest['files']['.dockerignore']=digest(after_ignore)
    manifest['context_patch']='registry-include-v1'
    after_manifest=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    if digest(after_ignore)!=NEW_IGNORE_SHA or digest(after_manifest)!=NEW_MANIFEST_SHA:
        raise ValueError('补丁输出与预先核验摘要不同，未写入')
    backup=root.parent/(root.name+'-contextfix-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir()
    (backup/'.dockerignore').write_bytes(before_ignore)
    (backup/'genescope2_manifest.json').write_bytes(before_manifest)
    try:
        atomic_bytes(ignore_path,after_ignore)
        atomic_bytes(manifest_path,after_manifest)
        verify_files(root,manifest)
    except Exception:
        atomic_bytes(ignore_path,before_ignore)
        atomic_bytes(manifest_path,before_manifest)
        raise
    return {'patched':True,'backup':str(backup),'files_verified':len(manifest['files']),
            'changed_manifest_entries':['.dockerignore'],'model_and_dataset_hashes_changed':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release_directory',type=Path)
    args=parser.parse_args()
    print(json.dumps(repair(args.release_directory),ensure_ascii=False,indent=2))
