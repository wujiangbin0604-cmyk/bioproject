"""本地发布包只读校验，保留原模型加载器的独立可信摘要验证。"""
import hashlib
import json
from pathlib import Path, PurePosixPath


def digest(path):
    """流式计算文件SHA-256，避免把大工件读入内存。"""
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def verify(root):
    """校验发布文件，不覆盖本地新增数据、模型或实验记录。"""
    root = Path(root).resolve()
    manifest_path = root / 'local_bundle_manifest.json'
    if not manifest_path.is_file():
        return {'bundle': False, 'message': '源码目录：没有本地发布包清单'}
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('raw_data_included') is not False or not manifest.get('files'):
        raise ValueError('本地发布清单格式无效')
    for relative, expected in manifest['files'].items():
        part = PurePosixPath(relative)
        if part.is_absolute() or '..' in part.parts or '\\' in relative or ':' in relative:
            raise ValueError('发布清单包含不安全路径')
        target = root.joinpath(*part.parts)
        if any(p.is_symlink() for p in [target, *target.parents] if p.is_relative_to(root)) or not target.resolve().is_relative_to(root):
            raise ValueError('发布目录包含不安全链接')
        if not target.is_file() or digest(target) != expected:
            raise ValueError(f'文件校验失败：{relative}，请重新解压原发布包')
    return {'bundle': True, 'version': manifest['version'], 'verified_files': len(manifest['files'])}
