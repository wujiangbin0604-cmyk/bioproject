"""Read-only provenance of research source, fixed split, frozen artifacts and historical results."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports/genescope2_protected_before.json'
def snapshot():
    files = list(ROOT.glob('*.py')) + list((ROOT / 'deployment').glob('*.py'))
    files += list((ROOT / 'deployment/models').rglob('*')) + [ROOT / 'data/split_manifest.json']
    files += [p for p in (ROOT / 'results').rglob('*') if 'lab_experiments' not in p.parts]
    return {str(p.relative_to(ROOT)): hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()
            for p in files if p.is_file() and '__pycache__' not in p.parts}

if __name__ == '__main__':
    current = snapshot()
    OUTPUT.parent.mkdir(exist_ok=True)
    if '--verify' in sys.argv:
        before = json.loads(OUTPUT.read_text(encoding='utf-8'))
        changed = [k for k, v in before.items() if current.get(k) != v]
        report={'protected_files': len(before), 'changed': changed}
        (ROOT/'reports/genescope2_protected_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        sys.exit(bool(changed))
    elif not OUTPUT.exists():
        OUTPUT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Protected baseline: {len(current)} files')
