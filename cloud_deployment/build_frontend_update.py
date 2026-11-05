"""Package a built frontend as a small verified update for an existing GeneScope 2 server."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(name='GeneScope2_UI_20261104_v2', instructions=None, public_access=False):
    if not name.replace('_', '').replace('-', '').isalnum():
        raise ValueError('发布名仅接受字母、数字、横线和下划线')
    files = sorted(p for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file())
    if not files or not (ROOT / 'frontend/dist/index.html').is_file():
        raise ValueError('请先执行 npm --prefix frontend run build')
    instructions = Path(instructions) if instructions else ROOT / 'cloud_deployment/FRONTEND_UPDATE.md'
    if not instructions.is_file():
        raise ValueError('缺少更新说明文件')
    def digest(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest = {'schema_version':1, 'scope':'frontend/dist', 'release':name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'files':{p.relative_to(ROOT).as_posix():digest(p) for p in files}}
    tools = {'update_frontend.py': ROOT / 'cloud_deployment/update_frontend.py', 'FRONTEND_UPDATE.md': instructions}
    if public_access:
        tools.update({name: ROOT / 'cloud_deployment' / name for name in ('apply_server_update.py', 'configure_public_access.py')})
        manifest.update(website_access='public', tools={name: digest(path) for name, path in tools.items()})
    folder = ROOT / 'cloud_deployment/dist'
    folder.mkdir(exist_ok=True)
    destination = folder / (name + '.zip')
    if destination.exists():
        raise FileExistsError('不覆盖已有发布包，请使用新的发布名')
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr('frontend_update.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, path in tools.items():
            archive.write(path, name)
    checksum = digest(destination)
    # sha256sum on Linux treats a CR before LF as part of the filename.
    destination.with_suffix('.zip.sha256').write_bytes((checksum + '  ' + destination.name + '\n').encode('ascii'))
    print(json.dumps({'archive':str(destination), 'bytes':destination.stat().st_size, 'sha256':checksum, 'frontend_files':len(files)}, ensure_ascii=False), flush=True)
    return destination


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--name', default='GeneScope2_UI_20261104_v2')
    parser.add_argument('--instructions', type=Path, help='此版本的上传、更新和回滚说明')
    parser.add_argument('--public-access', action='store_true', help='包含取消现有网站登录验证的网关工具与组合更新器')
    args = parser.parse_args()
    build(args.name, args.instructions, args.public_access)
