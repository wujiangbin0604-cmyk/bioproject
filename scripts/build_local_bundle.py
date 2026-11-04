"""从Git索引构建可审查的本地运行包，加入已构建前端，不带私有缓存。"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def public_path(relative):
    """本地客户端允许的源码文件；即使误被跟踪也排除运行数据。"""
    part = PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or ':' in relative or '\\' in relative:
        return False
    if any(p in {'.git', 'node_modules', '__pycache__', 'wheelhouse', 'local_dist', 'experiment_runs', 'model_registry'} or p.startswith(('.venv', '.vendor', '.env')) for p in part.parts):
        return False
    if part.parts[0] in {'results', 'reports', 'design-reference'}:
        return False
    if part.parts[0] == 'datasets' and relative != 'datasets/registry.json':
        return False
    if part.parts[0] == 'data' and relative not in {'data/README.md', 'data/split_manifest.json'}:
        return False
    if relative.startswith('deployment/reports/') or relative.endswith(('.tar', '.tar.gz', '.zip', '.log', '.pyc')):
        return False
    return True


def git(*arguments):
    """读取索引原字节，避免混入其他未提交的本机改动。"""
    return subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}', *arguments], cwd=ROOT)


def build(output=None, allow_staged=False):
    """生成包含成品前端、源码、M1和校验清单的跨平台ZIP。"""
    staged = subprocess.run(['git', '-c', f'safe.directory={ROOT.as_posix()}', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if staged and not allow_staged:
        raise ValueError('索引中存在未提交文件；正式包请在提交后构建，预验收可加--allow-staged')
    files = git('ls-files', '-z').decode('utf-8').split('\0')
    content = {name: git('show', ':' + name) for name in files if name and public_path(name)}
    for required in ['genescope.py', 'start_local.cmd', 'local_runtime/app.py', 'requirements-local.lock.txt']:
        if required not in content:
            raise ValueError(f'运行入口尚未加入Git索引：{required}')
    version = content['VERSION'].decode().strip()
    frontend = ROOT / 'frontend/dist'
    if not (frontend / 'index.html').is_file():
        raise ValueError('先运行 npm --prefix frontend run build')
    for path in sorted(frontend.rglob('*')):
        if path.is_symlink():
            raise ValueError('成品前端不接受符号链接')
        if path.is_file():
            content[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    # Validate the existing trusted M1 bytes before packaging; never rewrite its trust contract.
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(content['deployment/model_loader.py']).body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {'TRUSTED_MODEL_SHA256', 'TRUSTED_METADATA_SHA256'}}
    for name, key in [('M1_anova_top50.joblib', 'TRUSTED_MODEL_SHA256'), ('M1_anova_top50.metadata.json', 'TRUSTED_METADATA_SHA256')]:
        if hashlib.sha256(content['deployment/models/' + name]).hexdigest() != constants[key]:
            raise ValueError('Git中的M1工件与原可信摘要不同，拒绝打包')
    registry = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(content['deployment/lab_registry.py']).body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {'SPLIT_SHA', 'MODEL_SHA', 'CUSTOM_SOURCE_SHA'}}
    protected = {'data/split_manifest.json': registry['SPLIT_SHA'], **registry['CUSTOM_SOURCE_SHA']}
    protected.update({f'deployment/lab_models/{name}.joblib': checksum for name, checksum in registry['MODEL_SHA'].items() if name != 'M1'})
    for name, checksum in protected.items():
        if hashlib.sha256(content[name]).hexdigest() != checksum:
            raise ValueError(f'Git中的冻结文件摘要不同：{name}')
    for name in content:
        if name.endswith('.cmd'):
            content[name] = content[name].replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    manifest = {'schema_version': 1, 'version': version, 'created_at': datetime.now(timezone.utc).isoformat(),
                'source_commit': git('rev-parse', 'HEAD').decode().strip(), 'source_kind': 'staged-preview' if staged else 'committed',
                'raw_data_included': False, 'dynamic_models_included': False, 'prebuilt_frontend': True,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(content.items())}}
    content['local_bundle_manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    output = Path(output or ROOT / 'local_dist' / f'GeneScope2-local-v{version}.zip').resolve()
    if output.exists():
        raise FileExistsError('不覆盖已有运行包，请使用新输出路径')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in content.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            archive.writestr(info, data)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{checksum}  {output.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size, 'sha256': checksum,
                      'files': len(manifest['files']), 'source_commit': manifest['source_commit'], 'source_kind': manifest['source_kind']}, ensure_ascii=False), flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-staged', action='store_true')
    args = parser.parse_args()
    build(args.output, args.allow_staged)
