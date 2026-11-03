"""Download only official, fixed GEO URLs; never substitute synthetic matrices."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
URLS = {a.lower(): f'https://ftp.ncbi.nlm.nih.gov/geo/series/{prefix}/{a}/matrix/{a}_series_matrix.txt.gz'
        for a, prefix in [('GSE4290', 'GSE4nnn'), ('GSE44076', 'GSE44nnn'), ('GSE45827', 'GSE45nnn')]}

def download(dataset_id):
    folder = ROOT / 'datasets' / dataset_id / 'raw'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{dataset_id.upper()}_series_matrix.txt.gz'
    record = {'url': URLS[dataset_id], 'attempted_at': datetime.now(timezone.utc).isoformat()}
    try:
        if not target.exists():
            with urllib.request.urlopen(record['url'], timeout=45) as response, target.with_suffix('.part').open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
                    if output.tell() > 200 * 1024**2:
                        raise ValueError('Download exceeds 200 MiB limit')
            target.with_suffix('.part').replace(target)
        record.update(status='downloaded', bytes=target.stat().st_size,
                      sha256=hashlib.file_digest(target.open('rb'), 'sha256').hexdigest())
    except Exception as exc:
        record.update(status='pending', error=f'{type(exc).__name__}: {exc}')
    (folder / 'download.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(dataset_id, record, flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset_id', choices=[*URLS, 'all'], default='all', nargs='?')
    arguments = parser.parse_args()
    for key in URLS if arguments.dataset_id == 'all' else [arguments.dataset_id]:
        download(key)
