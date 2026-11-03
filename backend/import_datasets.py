"""Administrative local import; web API accepts uploads, never filesystem paths."""
import argparse
from backend.app.platform2.data import Datasets

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('dataset_id',choices=['all','pancan','gse4290','gse44076','gse45827'],default='all',nargs='?')
    args=parser.parse_args()
    datasets=Datasets()
    for key in [d['dataset_id'] for d in datasets.list()] if args.dataset_id=='all' else [args.dataset_id]:
        try:
            info=datasets.import_pancan() if key=='pancan' else datasets.import_geo(key,datasets.root/key/'raw'/f'{key.upper()}_series_matrix.txt.gz')
            print(key, info['status'], info['samples'], info['features'],info['class_counts'],info['quality'],flush=True)
        except Exception as exc:
            print(key,type(exc).__name__,str(exc),flush=True)
