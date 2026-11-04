"""Package a built frontend as a small verified update for an existing GeneScope 2 server."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(name='GeneScope2_UI_20261104_v2'):
    if not name.replace('_', '').replace('-', '').isalnum():
        raise ValueError('发布名仅接受字母、数字、横线和下划线')
    files = sorted(p for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file())
    if not files or not (ROOT / 'frontend/dist/index.html').is_file():
        raise ValueError('请先执行 npm --prefix frontend run build')
    def digest(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest = {'schema_version':1, 'scope':'frontend/dist', 'release':name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'files':{p.relative_to(ROOT).as_posix():digest(p) for p in files}}
    folder = ROOT / 'cloud_deployment/dist'
    folder.mkdir(exist_ok=True)
    destination = folder / (name + '.zip')
    if destination.exists():
        raise FileExistsError('不覆盖已有发布包，请使用新的发布名')
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr('frontend_update.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.write(ROOT / 'cloud_deployment/update_frontend.py', 'update_frontend.py')
        archive.write(ROOT / 'cloud_deployment/FRONTEND_UPDATE.md', 'FRONTEND_UPDATE.md')
    checksum = digest(destination)
    destination.with_suffix('.zip.sha256').write_text(checksum + '  ' + destination.name + '\n', encoding='ascii')
    print(json.dumps({'archive':str(destination), 'bytes':destination.stat().st_size, 'sha256':checksum, 'frontend_files':len(files)}, ensure_ascii=False), flush=True)
    return destination


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--name', default='GeneScope2_UI_20261104_v2')
    build(parser.parse_args().name)
