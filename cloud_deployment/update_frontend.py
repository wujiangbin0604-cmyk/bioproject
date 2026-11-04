"""Apply a verified static-frontend update; only frontend/dist and its manifest entries change.

The backup stays outside the Docker build context. No data, model, API, compose, TLS or
gateway files are changed. Both dry-run and rollback verify every existing release digest.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import uuid


def sha(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        return digest.hexdigest()


def checked(root, relative):
    root = Path(root).resolve()
    part = PurePosixPath(relative)
    if part.is_absolute() or not part.parts or '..' in part.parts or '\\' in relative or ':' in relative:
        raise ValueError('不安全的文件路径')
    path = root.joinpath(*part.parts)
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)) or not path.resolve().is_relative_to(root):
        raise ValueError('拒绝符号链接或越界路径')
    return path


def read_release(release):
    manifest_path = checked(release, 'genescope2_manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 2 or manifest.get('pancan_reserved_expression_included') is not False:
        raise ValueError('仅支持经过校验的GeneScope 2发布目录')
    if not manifest.get('files') or not any(p.startswith('frontend/dist/') for p in manifest['files']):
        raise ValueError('现有清单缺少前端文件')
    for relative, digest in manifest['files'].items():
        target = checked(release, relative)
        if not target.is_file() or sha(target) != digest:
            raise ValueError(f'原发布文件校验失败：{relative}')
    return manifest


def apply_update(payload, release, apply=False):
    payload, release = Path(payload).resolve(), Path(release).resolve()
    if payload == release or payload.is_relative_to(release) or release.is_relative_to(payload):
        raise ValueError('更新包与发布目录必须分开')
    manifest = read_release(release)
    update = json.loads(checked(payload, 'frontend_update.json').read_text(encoding='utf-8'))
    if update.get('schema_version') != 1 or update.get('scope') != 'frontend/dist' or not update.get('files'):
        raise ValueError('更新包范围无效')
    files = update['files']
    if 'frontend/dist/index.html' not in files:
        raise ValueError('更新包缺少index.html')
    for relative, digest in files.items():
        if not relative.startswith('frontend/dist/'):
            raise ValueError('更新包包含非前端文件')
        path = checked(payload, relative)
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f'更新文件校验失败：{relative}')
    contents = list(checked(payload, 'frontend/dist').rglob('*'))
    if any(p.is_symlink() for p in contents):
        raise ValueError('更新目录不接受符号链接')
    actual = {str(p.relative_to(payload).as_posix()) for p in contents if p.is_file()}
    if actual != set(files):
        raise ValueError('更新目录存在清单外文件')
    next_manifest = {**manifest, 'files': {p: h for p, h in manifest['files'].items() if not p.startswith('frontend/dist/')}}
    next_manifest['files'].update(files)
    next_manifest['frontend_update'] = {'release': update['release'], 'created_at': update['created_at']}
    if not apply:
        result = {'dry_run': True, 'frontend_files': len(files), 'other_release_files_changed': False}
        print(json.dumps(result), flush=True)
        return result
    backup = release.parent / ('frontend-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir()
    shutil.copy2(release / 'genescope2_manifest.json', backup / 'genescope2_manifest.json')
    stage = checked(release, 'frontend/.dist-stage-' + uuid.uuid4().hex)
    target = checked(release, 'frontend/dist')
    shutil.copytree(checked(payload, 'frontend/dist'), stage)
    # Neither persistent state nor old frontend bytes are deleted.
    target.rename(backup / 'dist')
    try:
        stage.rename(target)
        manifest_tmp = release / ('.frontend-manifest-' + uuid.uuid4().hex)
        manifest_tmp.write_text(json.dumps(next_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest_tmp.replace(release / 'genescope2_manifest.json')
        read_release(release)
    except Exception:
        if target.exists():
            target.rename(backup / 'failed-update-dist')
        (backup / 'dist').rename(target)
        shutil.copy2(backup / 'genescope2_manifest.json', release / 'genescope2_manifest.json')
        raise
    (backup / 'backup.json').write_text(json.dumps({'release': str(release), 'scope': 'frontend/dist'}), encoding='utf-8')
    result = {'updated': True, 'frontend_files': len(files), 'backup': str(backup), 'other_release_files_changed': False}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def rollback(release, backup):
    release, backup = Path(release).resolve(), Path(backup).resolve()
    read_release(release)
    marker = json.loads(checked(backup, 'backup.json').read_text(encoding='utf-8'))
    if marker != {'release': str(release), 'scope': 'frontend/dist'}:
        raise ValueError('备份不属于此发布目录')
    old = json.loads(checked(backup, 'genescope2_manifest.json').read_text(encoding='utf-8'))
    for relative, digest in old['files'].items():
        path = checked(backup, relative.removeprefix('frontend/')) if relative.startswith('frontend/dist/') else checked(release, relative)
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f'回滚文件校验失败：{relative}')
    saved = backup / ('updated-dist-' + uuid.uuid4().hex[:8])
    target = checked(release, 'frontend/dist')
    source = checked(backup, 'dist')
    if any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('备份目录不接受符号链接')
    stage = checked(release, 'frontend/.dist-rollback-' + uuid.uuid4().hex)
    shutil.copytree(source, stage)
    current_manifest = (release / 'genescope2_manifest.json').read_bytes()
    target.rename(saved)
    try:
        stage.rename(target)
        shutil.copy2(backup / 'genescope2_manifest.json', release / 'genescope2_manifest.json')
        read_release(release)
    except Exception:
        if target.exists():
            target.rename(backup / ('failed-rollback-' + uuid.uuid4().hex[:8]))
        saved.rename(target)
        (release / 'genescope2_manifest.json').write_bytes(current_manifest)
        raise
    print(json.dumps({'rolled_back': True, 'release': str(release)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--payload', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--apply', action='store_true', help='默认仅校验，显式应用时替换静态前端')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if args.rollback:
        rollback(args.release, args.rollback)
    else:
        apply_update(args.payload, args.release, args.apply)
